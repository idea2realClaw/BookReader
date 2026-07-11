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
import time

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
        self.speed = 1.0  # 朗读倍速（桌面端生效：驱动 pyttsx3 rate）
        self._stop_event = None  # 当前朗读会话的停止事件（供回调使用）

    # 桌面端基础语速（rate≈160 接近自然朗读）；实际 rate = BASE_RATE * speed
    _BASE_RATE = 160

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
        self._stop_event = stop_event
        if self._is_mobile():
            # 移动端（安卓/iOS）走在线 gTTS + 系统播放器
            return await self._speak_gtts(text, stop_event)
        # 桌面端优先离线 pyttsx3
        return await self._speak_desktop(text, stop_event)

    def stop(self):
        # 桌面端 pyttsx3：停止由 started-word 回调检查 stop_event 触发 eng.stop()，
        # 无需在此直接操作引擎（引擎位于朗读线程内，外部直接 stop 易死锁）。
        # 移动端：关闭本地 HTTP 服务与系统播放器进程。
        self._stop_process()

    # ---- 桌面端：pyttsx3（离线） ----
    async def _speak_desktop(self, text: str, stop_event) -> float:
        """桌面端离线朗读（Windows SAPI / macOS NSSpeech / Linux espeak）。

        关键修复：pyttsx3 在 worker 线程里用阻塞的 runAndWait() 会与 SAPI 的 COM
        回调产生时序竞争、偶发死锁（表现为"只有第一句有声/整页卡死"）。因此改用
        官方非阻塞模式 startLoop(False) + iterate() 在独立线程里轮询，彻底规避
        阻塞死锁；停止信号由 started-word 回调里的 eng.stop() 触发。
        """
        duration = _estimate_duration(text)
        import pyttsx3

        def _run():
            try:
                eng = pyttsx3.init()
            except Exception as ex:
                print(f"[TTS] pyttsx3 init 失败（回退 gTTS）: {ex}")
                return
            try:
                try:
                    eng.setProperty("rate", int(self._BASE_RATE * max(0.5, self.speed)))
                except Exception:
                    pass

                # 朗读中收到停止信号则中断当前朗读（回调在 SAPI 工作线程触发，安全）
                def _on_word(name):
                    if stop_event.is_set():
                        try:
                            eng.stop()
                        except Exception:
                            pass

                try:
                    eng.connect("started-word", _on_word)
                except Exception:
                    pass

                # 整段一次性朗读（不再逐句 say，避免 SAPI 逐句重置导致的静音）
                eng.say(text)
                try:
                    # 非阻塞轮询模式（首选，避免线程死锁）
                    eng.startLoop(False)
                    while True:
                        if stop_event.is_set():
                            try:
                                eng.stop()
                            except Exception:
                                pass
                            break
                        try:
                            busy = eng.isBusy()
                        except Exception:
                            busy = False
                        if not busy:
                            break
                        try:
                            eng.iterate()
                        except Exception:
                            break
                        time.sleep(0.02)
                    try:
                        eng.endLoop()
                    except Exception:
                        pass
                except Exception:
                    # 极旧 pyttsx3 无 startLoop/iterate：退回阻塞 runAndWait
                    try:
                        eng.say(text)
                        eng.runAndWait()
                    except Exception as ex:
                        print(f"[TTS] pyttsx3 朗读错误: {ex}")
            finally:
                try:
                    eng.stop()
                except Exception:
                    pass

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
