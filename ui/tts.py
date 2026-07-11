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
- 移动端（Android）：合成的 mp3 经本地 HTTP 服务（127.0.0.1，无需 INTERNET 权限）
  交给系统播放器播放。
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
    async def speak(self, text: str, stop_event) -> float:
        """朗读 text，返回估算时长（秒）。stop_event 置位时尽快停止。"""
        text = (text or "").strip()
        if not text:
            return 0.0
        if self._is_mobile():
            return await self._speak_mobile(text, stop_event)
        return await self._speak_edge(text, stop_event)

    def stop(self):
        # 桌面端：停止 pygame 播放；移动端：关闭本地 HTTP 服务
        self._stop_pygame()
        self._stop_process()
        self._shutdown_server()

    # ==================================================================
    # 桌面端：Edge TTS 合成 + pygame 应用内播放
    # ==================================================================
    async def _speak_edge(self, text: str, stop_event) -> float:
        if _edge_lite_synthesize is None:
            # websockets 缺失（理论上桌面不会发生）：仅按节奏停顿
            duration = _estimate_duration(text)
            await self._wait(duration, stop_event)
            return duration

        duration = _estimate_duration(text)
        mp3 = await _edge_lite_synthesize(
            text, self._voice_id(text), _rate_string(self.speed)
        )
        if mp3 is None:
            await self._wait(duration, stop_event)
            return duration
        try:
            await self._play_pygame(mp3, stop_event, duration)
        finally:
            self._shutdown_server()
            try:
                if mp3 and os.path.exists(mp3):
                    os.unlink(mp3)
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
    async def _speak_mobile(self, text: str, stop_event) -> float:
        duration = _estimate_duration(text)
        mp3 = await self._synthesize_mobile(text)
        if mp3 is None:
            await self._wait(duration, stop_event)
            return duration
        try:
            self._play_via_local_server(mp3)
            await self._wait(duration, stop_event)
        finally:
            self._shutdown_server()
            try:
                if mp3 and os.path.exists(mp3):
                    os.unlink(mp3)
            except Exception:
                pass
        return duration

    async def _synthesize_mobile(self, text: str):
        """移动端合成：优先 Edge TTS（真实男/女声+倍速），失败回退 gTTS。"""
        if _edge_lite_synthesize is not None:
            try:
                mp3 = await _edge_lite_synthesize(
                    text, self._voice_id(text), _rate_string(self.speed)
                )
                if mp3:
                    return mp3
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
