"""
跨平台 TTS 引擎（Edge TTS 统一后端，纯 Python 实现，可在安卓打包）。

合成：所有平台统一使用 Edge TTS（微软在线语音），由 ui/edge_tts_lite 提供。
      edge_tts_lite 仅依赖 websockets（纯 Python，Flet 安卓打包环境可安装），
      完整复刻 edge_tts 协议，因此安卓端也能用男/女声 + 倍速，
      且无需 pyjnius、无需第三方 APK（如 ag2s/TTS）、无需官方 edge_tts 包
      （后者顶层 import aiohttp → 依赖安卓缺失的 multidict/frozenlist wheel）。
      - 男声默认：zh-CN-YunyangNeural；女声默认：zh-CN-XiaoxiaoNeural。
      - 语速通过 Edge TTS 的 rate 参数控制（如 +20%）。

播放：
- 桌面端（Windows/macOS/Linux）：pygame 应用内播放，不调用外部播放器（如 vlc）。
- 移动端（Android）：用 flet_audio（Flet 官方音频控件，基于 Flutter audioplayers，
  原生支持 Android，无 C 扩展依赖）做应用内播放合成的 mp3 文件 —— 可靠出声。
  （早期用 `am start` 拉系统播放器，但系统播放器打开音频后默认不自动播放，
   导致"朗读流程在跑却听不到声"，故改用 flet_audio。）flet_audio 缺失时回退
  本地 HTTP + 系统播放器。
容错：Edge 合成失败（无网络等）时，移动端回退 gTTS，桌面端按估算时长静默停顿，
      保证朗读节奏正常。
"""

import asyncio
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import Optional

# Edge TTS 轻量客户端（纯 Python，可打包）。若 websockets 缺失则为本模块导入失败时置 None。
try:
    from .edge_tts_lite import synthesize as _edge_lite_synthesize
except Exception:  # pragma: no cover - websockets 缺失时
    _edge_lite_synthesize = None

# gTTS 仅作为移动端 Edge 合成失败时的兜底
try:
    from gtts import gTTS as _GTTS
except Exception:  # pragma: no cover
    _GTTS = None

# flet_audio：Flet 官方音频控件（基于 Flutter audioplayers），原生支持 Android，
# 无需 pygame / C 扩展。安卓端用它做应用内播放，替代不可靠的 `am start` 系统播放器
# （后者打开音频后默认不自动播放 → 朗读流程在跑却听不到声）。缺失时回退 am start。
try:
    import flet_audio as _FTA
except Exception:  # pragma: no cover
    _FTA = None

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 音色映射：男 / 女（缺省男）。各种语言给出 Edge TTS 标准神经语音。
VOICE_MAP = {
    "male": {
        "zh": "zh-CN-YunyangNeural",      # 云扬（男）
        "en": "en-US-GuyNeural",          # Guy（男）
    },
    "female": {
        "zh": "zh-CN-XiaoxiaoNeural",     # 晓晓（女）
        "en": "en-US-AriaNeural",         # Aria（女）
    },
}


def _detect_lang(text: str) -> str:
    """简易语言检测：含中文用 zh，否则 en。"""
    return "zh" if _CJK_RE.search(text) else "en"


def estimate_duration(text: str) -> float:
    """公开：估算朗读时长（秒），供调用方做逐句高亮节奏控制。"""
    return _estimate_duration(text)


def _estimate_duration(text: str) -> float:
    """估算朗读时长（秒）。中文约 6 字/秒，英文约 2.5 词/秒。"""
    if _CJK_RE.search(text):
        chars = len(_CJK_RE.findall(text))
        return max(1.0, chars / 6.0)
    words = len(text.split())
    return max(1.0, words / 2.5)


def _rate_string(speed: float) -> str:
    """将倍速（>=1.0）转换为 Edge TTS rate 参数（如 +20%）。"""
    pct = int(round((max(1.0, speed) - 1.0) * 100))
    return f"+{pct}%"


class TTSEngine:
    def __init__(self, page=None):
        self.page = page
        self._process = None
        self._httpd = None
        self.speed = 1.2        # 朗读倍速（1.0~2.0）
        self.voice = "male"     # 音色：male / female（缺省男）
        self._stop_event = None
        self._audio = None  # flet_audio.Audio 控件（安卓端应用内播放，懒创建）

    # ---- 平台判断 ----
    def _is_mobile(self) -> bool:
        try:
            return bool(self.page.platform.is_mobile())
        except Exception:
            return False

    def _voice_id(self, text: str) -> str:
        lang = _detect_lang(text)
        return VOICE_MAP.get(self.voice, VOICE_MAP["male"]).get(lang, VOICE_MAP["male"]["zh"])

    # ---- 公开接口 ----
    async def speak(self, text: str, stop_event, prefetched_path: Optional[str] = None) -> float:
        """朗读 text，返回估算时长（秒）。stop_event 置位时尽快停止。
        prefetched_path：已合成好的 mp3 临时文件路径（由 synthesize_to_path 预取），
        传入可跳过联网合成，实现翻页无缝衔接。"""
        text = (text or "").strip()
        if not text:
            return 0.0
        if self._is_mobile():
            return await self._speak_mobile(text, stop_event, prefetched_path)
        return await self._speak_edge(text, stop_event, prefetched_path)

    def stop(self):
        # 桌面端：停止 pygame 播放；移动端：关闭本地 HTTP 服务 + 停止 flet_audio
        self._stop_pygame()
        self._stop_process()
        self._shutdown_server()
        self._request_flet_audio_stop()

    def _request_flet_audio_stop(self):
        """异步停止 flet_audio 播放（flet_audio 的 pause/release 是协程，
        需投到事件循环里执行，避免在同步 stop() 中直接 await）。"""
        a = self._audio
        if a is None:
            return
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._stop_flet_audio_async(a))
        except Exception:
            pass

    async def _stop_flet_audio_async(self, a):
        try:
            await a.pause()
        except Exception:
            pass
        try:
            await a.release()
        except Exception:
            pass

    def _get_flet_audio(self):
        """懒创建并挂载一个 flet_audio.Audio 控件（应用内播放，原生支持 Android）。"""
        if self._audio is None:
            self._audio = _FTA.Audio(
                src="",
                volume=1.0,
                release_mode=_FTA.ReleaseMode.STOP,
            )
            try:
                self.page.services.append(self._audio)
                self.page.update()
            except Exception as ex:
                print(f"[TTS] 挂载 flet_audio 控件失败: {ex}")
        return self._audio

    async def _play_flet_audio(self, mp3_path: str, duration: float, stop_event):
        """用 flet_audio 播放本地 mp3 文件，等待播放结束（或停止信号）。"""
        audio = self._get_flet_audio()
        audio.src = mp3_path
        audio.update()
        await audio.play()
        step = 0.1
        elapsed = 0.0
        limit = duration + 2.0  # 给真实播放一点余量，避免提前切断尾音
        while elapsed < limit and not stop_event.is_set():
            await asyncio.sleep(step)
            elapsed += step
        try:
            await audio.pause()
        except Exception:
            pass
        try:
            await audio.release()
        except Exception:
            pass

    async def synthesize_to_path(self, text: str) -> Optional[str]:
        """仅合成（不播放），返回临时 mp3 文件路径；失败或移动端返回 None。
        调用方负责在播放后 unlink 该临时文件。用于翻页前并行预取下一页音频，
        从而消除翻页后的联网合成等待。"""
        if self._is_mobile():
            # 移动端：直接合成到临时文件并返回路径（flet_audio 可播放本地文件，
            # 翻页前并行预取即可消除联网合成等待，与桌面端一致）。
            return await self._synthesize_mobile_to_file(text)
        text = (text or "").strip()
        if not text:
            return None
        if _edge_lite_synthesize is None:
            return None
        try:
            mp3_bytes = await _edge_lite_synthesize(
                text, self._voice_id(text), _rate_string(self.speed)
            )
        except Exception as ex:
            print(f"[TTS] 预取合成失败: {ex}")
            return None
        if not mp3_bytes:
            return None
        fd, mp3_path = tempfile.mkstemp(suffix=".mp3")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(mp3_bytes)
        except Exception:
            try:
                os.unlink(mp3_path)
            except Exception:
                pass
            return None
        return mp3_path

    # ==================================================================
    # 桌面端：Edge TTS 合成 + pygame 应用内播放
    # ==================================================================
    async def _speak_edge(self, text: str, stop_event, prefetched_path: Optional[str] = None) -> float:
        duration = _estimate_duration(text)
        # 优先使用预取好的音频（翻页前已并行合成），跳过联网等待
        if prefetched_path and os.path.exists(prefetched_path):
            try:
                await self._play_pygame(prefetched_path, stop_event, duration)
            finally:
                self._shutdown_server()
            return duration

        if _edge_lite_synthesize is None:
            # websockets 缺失（理论上桌面不会发生）：仅按节奏停顿
            await self._wait(duration, stop_event)
            return duration

        mp3_bytes = await _edge_lite_synthesize(
            text, self._voice_id(text), _rate_string(self.speed)
        )
        if mp3_bytes is None:
            await self._wait(duration, stop_event)
            return duration
        # edge_tts_lite 返回的是 mp3 字节，必须写入临时文件再交给 pygame 播放
        # （pygame.mixer.music.load 只接受文件路径，直接传字节会报
        #  "No file 'b'\\xff\\xf3...'"）。
        fd, mp3_path = tempfile.mkstemp(suffix=".mp3")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(mp3_bytes)
            try:
                await self._play_pygame(mp3_path, stop_event, duration)
            finally:
                self._shutdown_server()
                try:
                    if os.path.exists(mp3_path):
                        os.unlink(mp3_path)
                except Exception:
                    pass
        finally:
            try:
                if os.path.exists(mp3_path):
                    os.unlink(mp3_path)
            except Exception:
                pass
        return duration

    async def _play_pygame(self, mp3_path: str, stop_event, duration: float):
        try:
            import pygame
        except Exception as ex:
            print(f"[TTS] pygame 不可用: {ex}，仅按节奏停顿")
            await self._wait(duration, stop_event)
            return

        try:
            pygame.mixer.init()
        except Exception as ex:
            print(f"[TTS] pygame mixer 初始化失败: {ex}")
            await self._wait(duration, stop_event)
            return

        try:
            # 倍速：用略高的播放频率模拟（会伴随轻微音调升高，属淘宝语音式加速）。
            base = 44100
            if self.speed > 1.02:
                cand = [48000, 44100, 22050]
                for f in cand:
                    if f >= base * self.speed:
                        freq = f
                        break
                else:
                    freq = 48000
                try:
                    pygame.mixer.quit()
                    pygame.mixer.init(frequency=freq)
                except Exception:
                    pass

            try:
                pygame.mixer.music.load(mp3_path)
                pygame.mixer.music.play()
            except Exception as ex:
                print(f"[TTS] pygame 播放失败: {ex}")
                return

            step = 0.1
            elapsed = 0.0
            while True:
                if stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                if not pygame.mixer.music.get_busy():
                    break
                if elapsed >= duration + 5.0:
                    pygame.mixer.music.stop()
                    break
                await asyncio.sleep(step)
                elapsed += step
        finally:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def _stop_pygame(self):
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    # ==================================================================
    # 移动端：Edge TTS（失败回退 gTTS）+ 本地 HTTP 服务交给系统播放器
    # ==================================================================
    async def _speak_mobile(self, text: str, stop_event, prefetched_path=None) -> float:
        """移动端朗读：优先用 flet_audio 应用内播放（可靠出声）；flet_audio 缺失时
        回退到本地 HTTP + 系统播放器。prefetched_path 为预取好的 mp3 文件，传给它
        可跳过联网合成、实现翻页无缝衔接。"""
        duration = _estimate_duration(text)
        mp3 = prefetched_path if (prefetched_path and os.path.exists(prefetched_path)) \
            else await self._synthesize_mobile_to_file(text)
        if mp3 is None:
            await self._wait(duration, stop_event)
            return duration
        # 优先用 flet_audio 应用内播放（可靠出声）；缺失则回退系统播放器
        if _FTA is not None:
            try:
                await self._play_flet_audio(mp3, duration, stop_event)
            except Exception as ex:
                print(f"[TTS] flet_audio 播放失败，回退系统播放器: {ex}")
                try:
                    self._play_via_local_server(mp3)
                    await self._wait(duration, stop_event)
                finally:
                    self._shutdown_server()
        else:
            try:
                self._play_via_local_server(mp3)
                await self._wait(duration, stop_event)
            finally:
                self._shutdown_server()
        # 清理音频文件：预取文件（prefetched_path）由 _read_all 负责回收，这里只删自行合成的
        if mp3 != prefetched_path:
            try:
                if os.path.exists(mp3):
                    os.unlink(mp3)
            except Exception:
                pass
        return duration

    async def _synthesize_mobile_to_file(self, text: str):
        """移动端合成：优先 Edge TTS（真实男/女声+倍速），失败回退 gTTS；返回 mp3 文件路径。"""
        if _edge_lite_synthesize is not None:
            try:
                mp3 = await _edge_lite_synthesize(
                    text, self._voice_id(text), _rate_string(self.speed)
                )
                if mp3:
                    fd, path = tempfile.mkstemp(suffix=".mp3")
                    try:
                        with os.fdopen(fd, "wb") as f:
                            f.write(mp3)
                    except Exception:
                        try:
                            os.unlink(path)
                        except Exception:
                            pass
                        return None
                    return path
            except Exception as ex:
                print(f"[TTS] 安卓 Edge 合成失败，回退 gTTS: {ex}")
        return await self._synthesize_gtts(text)

    async def _synthesize_gtts(self, text: str):
        if _GTTS is None:
            return None
        lang = "zh-cn" if _CJK_RE.search(text) else "en"
        try:
            fd, mp3_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            # tld="com" 在中国大陆可达（tld="cn" 合成接口返回 404，不可用）
            await asyncio.to_thread(_GTTS(text=text, lang=lang, tld="com").save, mp3_path)
            return mp3_path
        except Exception as ex:
            print(f"[TTS] gTTS 合成失败: {ex}")
            try:
                if "mp3_path" in dir() and os.path.exists(mp3_path):
                    os.unlink(mp3_path)
            except Exception:
                pass
            return None

    def _play_via_local_server(self, mp3_path: str):
        import functools
        import http.server
        import socket
        import socketserver

        directory = os.path.dirname(mp3_path)
        fname = os.path.basename(mp3_path)
        try:
            os.chmod(mp3_path, 0o644)
        except Exception:
            pass

        class _SilentHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        handler = functools.partial(_SilentHandler, directory=directory)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
        self._httpd = httpd
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        url = f"http://127.0.0.1:{port}/{fname}"
        try:
            self._process = subprocess.Popen(
                [
                    "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-t", "audio/mpeg",
                    "-d", url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[TTS] 安卓播放 URL: {url}")
        except Exception as ex:
            # 启动系统播放器失败（如非安卓环境）不应中断朗读节奏
            print(f"[TTS] 启动系统播放器失败: {ex}")

    def _shutdown_server(self):
        httpd = self._httpd
        self._httpd = None
        if httpd is None:
            return
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass

    # ==================================================================
    # 通用：按估算时长等待（可被打断）
    # ==================================================================
    async def _wait(self, duration: float, stop_event):
        elapsed = 0.0
        step = 0.1
        while elapsed < duration:
            if stop_event.is_set():
                self._stop_pygame()
                self._stop_process()
                break
            await asyncio.sleep(step)
            elapsed += step
        self._stop_pygame()
        self._stop_process()

    def _stop_process(self):
        p = self._process
        self._process = None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=1)
                except Exception:
                    p.kill()
        except Exception:
            pass
        self._shutdown_server()
