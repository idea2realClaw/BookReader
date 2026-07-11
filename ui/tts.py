"""
跨平台 TTS 引擎。

- 桌面端（Windows / Linux / macOS）：优先使用 pyttsx3 离线引擎
  （Windows 走系统 SAPI、macOS 走 NSSpeech、Linux 走 espeak），无需联网、稳定出声。
- 移动端（Android / iOS）：flet 0.85.3 没有内置音频控件，且安卓受 scoped storage
  限制，纯 Python 无法可靠地把应用私有目录的音频交给系统播放器。
  因此安卓端用 gTTS 在线合成 mp3，经本地 HTTP 服务（127.0.0.1，绕开 scoped storage，
  无需 INTERNET 权限）交给系统播放器播放；若合成失败则按估算时长静默停顿，
  保证朗读节奏正常（不会瞬间翻页）。

说明：安卓端"稳定、应用内可停止的原生朗读"需要 Flutter 原生 flutter_tts 控件
（自定义 Dart 桥接），纯 Python 方案为尽力而为。
"""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import threading

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _detect_lang(text: str) -> str:
    """简易语言检测：含中文用 zh-cn，否则 en。"""
    if _CJK_RE.search(text):
        return "zh-cn"
    return "en"


def estimate_duration(text: str) -> float:
    """公开：估算朗读时长（秒），供调用方做逐句高亮节奏控制。"""
    return _estimate_duration(text)


def _estimate_duration(text: str) -> float:
    """估算朗读时长（秒）。中文约 6 字/秒，英文约 12 词/秒。"""
    if _CJK_RE.search(text):
        chars = len(_CJK_RE.findall(text))
        return max(1.0, chars / 6.0)
    words = len(text.split())
    return max(1.0, words / 2.5)


class TTSEngine:
    def __init__(self, page=None):
        self.page = page
        self._process = None
        self._httpd = None
        self._pyttsx_engine = None
        self._pyttsx_lock = threading.Lock()

    # ---- 平台判断 ----
    def _is_windows(self) -> bool:
        return sys.platform == "win32"

    def _is_mobile(self) -> bool:
        try:
            return bool(self.page.platform.is_mobile())
        except Exception:
            return False

    # ---- 公开接口 ----
    async def speak(self, text: str, stop_event) -> float:
        """朗读 text，返回估算时长（秒）。stop_event 置位时尽快停止。"""
        text = (text or "").strip()
        if not text:
            return 0.0
        if self._is_mobile():
            # 移动端（安卓/iOS）走在线 gTTS + 系统播放器
            return await self._speak_gtts(text, stop_event)
        # 桌面端优先离线 pyttsx3
        return await self._speak_desktop(text, stop_event)

    def stop(self):
        # 桌面端 pyttsx3 立即停止当前朗读
        try:
            if self._pyttsx_engine is not None:
                self._pyttsx_engine.stop()
        except Exception:
            pass
        self._stop_process()

    # ---- 桌面端：pyttsx3（离线） ----
    def _get_pyttsx(self):
        """懒初始化并缓存 pyttsx3 引擎；不可用（无语音后端）时返回 None。"""
        if self._pyttsx_engine is not None:
            return self._pyttsx_engine
        try:
            import pyttsx3

            eng = pyttsx3.init()
            # 语速放缓一点，更接近自然朗读
            try:
                eng.setProperty("rate", 175)
            except Exception:
                pass
            self._pyttsx_engine = eng
            return eng
        except Exception as ex:
            print(f"[TTS] pyttsx3 初始化失败（将回退 gTTS）: {ex}")
            self._pyttsx_engine = False  # 标记失败，避免反复尝试
            return None

    async def _speak_desktop(self, text: str, stop_event) -> float:
        duration = _estimate_duration(text)
        eng = self._get_pyttsx()
        if eng is None:
            # 离线引擎不可用时回退到在线 gTTS（桌面端也有声）
            return await self._speak_gtts(text, stop_event)

        # 按句朗读，便于在句间响应停止事件
        sentences = re.split(r"(?<=[。！？!?])", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        def _run():
            for s in sentences:
                if stop_event.is_set():
                    break
                with self._pyttsx_lock:
                    try:
                        eng.say(s)
                        eng.runAndWait()
                    except Exception as ex:
                        print(f"[TTS] pyttsx3 朗读单句错误: {ex}")

        try:
            await asyncio.to_thread(_run)
        except Exception as ex:
            print(f"[TTS] pyttsx3 线程错误: {ex}")
        return duration

    # ---- 移动端：gTTS 在线合成 + 系统播放器 ----
    async def _speak_gtts(self, text: str, stop_event) -> float:
        duration = _estimate_duration(text)
        try:
            from gtts import gTTS
        except Exception as ex:
            print(f"[TTS] gtts 不可用: {ex}，仅按节奏停顿")
            await self._wait(duration, stop_event)
            return duration

        mp3_path = None
        try:
            fd, mp3_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            gTTS(text=text, lang=_detect_lang(text)).save(mp3_path)
        except Exception as ex:
            print(f"[TTS] gTTS 合成失败（可能无网络）: {ex}")
            await self._wait(duration, stop_event)
            return duration

        try:
            if self._is_mobile():
                # 安卓：经本地 HTTP 服务交给系统播放器。
                # 直接 file:// 受 scoped storage 限制无法被其他应用读取，
                # 走 http://127.0.0.1 可绕开该限制（无需 INTERNET 权限）。
                self._play_via_local_server(mp3_path)
            else:
                self._launch_player(mp3_path)
        except Exception as ex:
            print(f"[TTS] 播放启动失败: {ex}")

        # 等整页朗读时长（让系统播放器有足够时间播放），再清理
        await self._wait(duration, stop_event)

        # 清理：关闭本地服务并删除临时文件
        self._shutdown_server()
        try:
            if mp3_path and os.path.exists(mp3_path):
                os.unlink(mp3_path)
        except Exception:
            pass
        return duration

    def _play_via_local_server(self, mp3_path: str):
        """安卓：起一个本地 HTTP 服务托管 mp3，再让系统播放器打开该 URL。"""
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

    def _launch_player(self, mp3_path: str):
        if self._is_mobile():
            self._process = subprocess.Popen(
                [
                    "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-t", "audio/mpeg",
                    "-d", f"file://{mp3_path}",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            self._process = subprocess.Popen(
                ["afplay", mp3_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            self._process = subprocess.Popen(
                ["xdg-open", mp3_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    async def _wait(self, duration: float, stop_event):
        elapsed = 0.0
        step = 0.1
        while elapsed < duration:
            if stop_event.is_set():
                self._stop_process()
                break
            await asyncio.sleep(step)
            elapsed += step
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
        # 同时关闭安卓本地 HTTP 服务（停止后不再提供音频流）
        self._shutdown_server()
