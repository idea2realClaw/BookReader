"""
跨平台 TTS 引擎（统一走 gTTS 在线合成）。

- 桌面端（Windows / Linux / macOS）与移动端（Android / iOS）均使用 gTTS 在线合成 mp3。
- 合成域名优先使用 .cn（translate.google.cn），若不可用（接口返回 404）则自动回退 .com
  （translate.google.com），二者在中国大陆均可访问，保证国内可用。
- 桌面端：合成后直接用系统播放器（Windows: 关联播放器 / macOS: afplay / Linux: paplay/aplay）
  同步播放，播完再翻页；停止时杀掉播放器进程即可中断。
- 移动端（安卓）：受 scoped storage 限制，纯 Python 无法可靠地把应用私有目录音频交给系统
  播放器，因此经本地 HTTP 服务（127.0.0.1，绕开 scoped storage，无需 INTERNET 权限）交给
  系统播放器播放；若合成失败则按估算时长静默停顿，保证朗读节奏正常（不会瞬间翻页）。

说明：移动端"稳定、应用内可停止的原生朗读"需要 Flutter 原生 flutter_tts 控件（自定义 Dart
桥接），纯 Python 方案为尽力而为。桌面端用系统播放器同步播放，停止可靠。
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
        self.speed = 1.0  # 朗读倍速（gTTS 在线合成不直接支持倍速，仅作预留）
        self._stop_event = None  # 当前朗读会话的停止事件（供回调使用）

    # 合成域名优先级：优先 .cn（大陆友好），失败回退 .com（大陆同样可达）
    _TTS_TLDS = ("cn", "com")

    # ---- 平台判断 ----
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
        # 桌面端与移动端统一走 gTTS 在线合成
        return await self._speak_gtts(text, stop_event)

    def stop(self):
        # 停止系统播放器进程 / 关闭安卓本地 HTTP 服务
        self._stop_process()

    # ---- 在线合成：gTTS ----
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
            lang = _detect_lang(text)
            # 优先 .cn，失败自动回退 .com（均在中国大陆可达）
            saved = None
            for tld in self._TTS_TLDS:
                try:
                    gTTS(text=text, lang=lang, tld=tld).save(mp3_path)
                    saved = tld
                    break
                except Exception as ex:
                    print(f"[TTS] gTTS 合成失败(tld={tld}): {ex}")
            if saved is None:
                print(f"[TTS] gTTS 全部域名合成失败（可能无网络），仅按节奏停顿")
                await self._wait(duration, stop_event)
                return duration
            print(f"[TTS] gTTS 合成成功(tld={saved}, lang={lang})")
        except Exception as ex:
            print(f"[TTS] gTTS 合成异常（可能无网络）: {ex}")
            await self._wait(duration, stop_event)
            return duration

        try:
            if self._is_mobile():
                # 安卓：经本地 HTTP 服务交给系统播放器（绕开 scoped storage）
                self._play_via_local_server(mp3_path)
            else:
                # 桌面：用系统播放器同步播放（播完再翻页，停止可靠）
                self._launch_and_wait_player(mp3_path, stop_event, duration)
        except Exception as ex:
            print(f"[TTS] 播放启动失败: {ex}")
            await self._wait(duration, stop_event)

        # 清理：关闭安卓本地服务并删除临时文件
        self._shutdown_server()
        try:
            if mp3_path and os.path.exists(mp3_path):
                os.unlink(mp3_path)
        except Exception:
            pass
        return duration

    def _launch_and_wait_player(self, mp3_path: str, stop_event, duration: float):
        """桌面端：启动系统播放器并同步等待播放结束（或停止信号）。"""
        if sys.platform == "win32":
            # os.startfile 为同步阻塞（直到关联的播放器关闭）
            self._process = ("startfile", mp3_path)
            try:
                os.startfile(mp3_path)  # type: ignore[attr-defined]
            except Exception as ex:
                print(f"[TTS] Windows 启动播放器失败: {ex}")
                self._process = None
        elif sys.platform == "darwin":
            self._process = subprocess.Popen(
                ["afplay", mp3_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # Linux：优先 paplay/aplay（同步播放、可终止），否则回退 xdg-open
            player = None
            for cand in ("paplay", "aplay", "mpg123", "play"):
                if self._which(cand):
                    player = cand
                    break
            if player:
                self._process = subprocess.Popen(
                    [player, mp3_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                self._process = subprocess.Popen(
                    ["xdg-open", mp3_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

        # 同步等待：播放器进程结束，或收到停止信号
        if isinstance(self._process, tuple) and self._process[0] == "startfile":
            # Windows os.startfile 已同步阻塞；只需等待停止信号
            self._wait_sync(stop_event, duration)
        else:
            p = self._process
            step = 0.1
            elapsed = 0.0
            while True:
                if stop_event.is_set():
                    self._stop_process()
                    break
                if p is None or p.poll() is not None:
                    break
                if elapsed >= duration + 5.0:
                    # 播放器异常未退出（如 xdg-open 仅拉起外部程序）：超时退出
                    self._stop_process()
                    break
                time.sleep(step)
                elapsed += step

    @staticmethod
    def _which(name: str) -> bool:
        from shutil import which
        return which(name) is not None

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

    async def _wait(self, duration: float, stop_event):
        """按估算时长等待（合成失败时的兜底停顿）。"""
        elapsed = 0.0
        step = 0.1
        while elapsed < duration:
            if stop_event.is_set():
                self._stop_process()
                break
            await asyncio.sleep(step)
            elapsed += step
        self._stop_process()

    def _wait_sync(self, stop_event, duration: float):
        """同步等待（Windows os.startfile 已阻塞，这里仅响应停止信号）。"""
        elapsed = 0.0
        step = 0.1
        while elapsed < duration + 5.0:
            if stop_event.is_set():
                self._stop_process()
                break
            time.sleep(step)
            elapsed += step

    def _stop_process(self):
        # Windows os.startfile 无法终止外部播放器（进程句柄不可用），仅关闭安卓服务
        p = self._process
        self._process = None
        if p is None:
            return
        if isinstance(p, tuple):
            # Windows startfile：记录的是 ('startfile', path)，无法直接终止
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
