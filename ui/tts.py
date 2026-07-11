"""
跨平台 TTS 引擎（基于 Edge TTS，应用内播放）。

- 合成：Edge TTS（微软在线语音），免费、支持中文男女声、可调语速、在中国大陆可访问。
  - 男声默认：zh-CN-YunyangNeural；女声默认：zh-CN-XiaoxiaoNeural。
  - 语速通过 Edge TTS 的 rate 参数控制（如 +20%），中英文本自动选对应语音。
- 桌面端（Windows / macOS / Linux）：用 pygame 在应用内播放合成出的 mp3，
  不调用任何外部播放器（如 vlc）；语速滑块通过 pygame 播放频率即时生效。
- 移动端（Android）：受 scoped storage 限制，纯 Python 无法可靠地把应用私有目录音频
  交给系统播放器，因此经本地 HTTP 服务（127.0.0.1，绕开 scoped storage，无需 INTERNET
  权限）交给系统播放器播放；语速已烘焙进 mp3（Edge TTS rate），系统播放器按原速播放即可。
- 若 Edge TTS 合成失败（无网络等），按估算时长静默停顿，保证朗读节奏正常（不会瞬间翻页）。
"""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

import edge_tts

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 音色映射：男 / 女（缺省男）。每种语言给出 Edge TTS 标准神经语音。
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
    """估算朗读时长（秒）。中文约 6 字/秒，英文约 2.5 词/秒（含 Edge TTS 语速后略调）。"""
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
        self._stop_event = stop_event

        duration = _estimate_duration(text)
        # 合成 mp3（Edge TTS）
        mp3_path = await self._synthesize(text)
        if mp3_path is None:
            # 合成失败：仅按节奏停顿
            await self._wait(duration, stop_event)
            return duration

        try:
            if self._is_mobile():
                self._play_via_local_server(mp3_path)
                await self._wait(duration, stop_event)
            else:
                await self._play_pygame(mp3_path, stop_event, duration)
        finally:
            self._shutdown_server()
            try:
                if mp3_path and os.path.exists(mp3_path):
                    os.unlink(mp3_path)
            except Exception:
                pass
        return duration

    def stop(self):
        # 桌面端：停止 pygame 播放；移动端：关闭本地 HTTP 服务与系统播放器
        self._stop_pygame()
        self._stop_process()
        self._shutdown_server()

    # ---- 合成（Edge TTS） ----
    async def _synthesize(self, text: str) -> str | None:
        voice = self._voice_id(text)
        rate = _rate_string(self.speed)
        try:
            fd, mp3_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            comm = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            await comm.save(mp3_path)
            print(f"[TTS] Edge TTS 合成成功 voice={voice} rate={rate}")
            return mp3_path
        except Exception as ex:
            print(f"[TTS] Edge TTS 合成失败（可能无网络）: {ex}")
            try:
                if "mp3_path" in dir() and os.path.exists(mp3_path):
                    os.unlink(mp3_path)
            except Exception:
                pass
            return None

    # ---- 桌面端：pygame 应用内播放（不调用外部播放器） ----
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
            # pygame 仅支持 22050/44100/48000，取最接近的合法值。
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

            # 等待播放结束或停止信号
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

    # ---- 移动端：本地 HTTP 服务 + 系统播放器 ----
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
