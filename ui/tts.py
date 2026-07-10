"""
跨平台 TTS 引擎。

- Windows 桌面：使用系统 SAPI（VBScript + cscript），离线、无需联网。
- Android / iOS / Linux / macOS：使用 gTTS 在线合成语音，再尝试播放。

说明：
flet 0.85.3 没有内置音频播放控件，且安卓受 scoped storage 限制，
纯 Python 无法可靠地把应用私有目录的音频交给系统播放器。
因此安卓端若 `am start` 无法出声，本模块会按估算时长 sleep，
保证朗读节奏正常（不会瞬间翻页），并把合成结果交给系统尝试播放。
如需安卓稳定出声，应接入 Flutter 原生 `flutter_tts`（自定义控件）。
"""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import time

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _detect_lang(text: str) -> str:
    """简易语言检测：含中文用 zh-cn，否则 en。"""
    if _CJK_RE.search(text):
        return "zh-cn"
    return "en"


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
        if self._is_windows():
            return await self._speak_windows(text, stop_event)
        return await self._speak_gtts(text, stop_event)

    def stop(self):
        self._stop_process()

    # ---- Windows: SAPI ----
    async def _speak_windows(self, text: str, stop_event) -> float:
        try:
            await asyncio.to_thread(self._speak_with_cscript, text, stop_event)
            return _estimate_duration(text)
        except Exception as ex:
            print(f"[TTS] Windows SAPI 错误: {ex}")
            await asyncio.sleep(1.0)
            return _estimate_duration(text)

    def _speak_with_cscript(self, text: str, stop_event):
        import tempfile as _tf
        safe = text[:200].replace('"', "'").replace("\n", " ").replace("\r", " ")
        vbs = (
            'Set speak = CreateObject("SAPI.SpVoice")\n'
            'speak.Rate = 2\n'
            f'speak.Speak "{safe}"\n'
        )
        fd, vbs_path = _tf.mkstemp(suffix=".vbs")
        with os.fdopen(fd, "w", encoding="ansi") as f:
            f.write(vbs)
        try:
            self._process = subprocess.Popen(
                ["cscript", "//nologo", vbs_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            while self._process.poll() is None:
                if stop_event.is_set():
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=1)
                    except Exception:
                        self._process.kill()
                    break
                time.sleep(0.1)
        finally:
            self._process = None
            try:
                os.unlink(vbs_path)
            except Exception:
                pass

    # ---- 其它平台: gTTS ----
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
            print(f"[TTS] gTTS 合成失败: {ex}")
            await self._wait(duration, stop_event)
            return duration

        try:
            self._launch_player(mp3_path)
        except Exception as ex:
            print(f"[TTS] 播放启动失败: {ex}")

        await self._wait(duration, stop_event)

        try:
            if mp3_path and os.path.exists(mp3_path):
                os.unlink(mp3_path)
        except Exception:
            pass
        return duration

    def _launch_player(self, mp3_path: str):
        if self._is_mobile():
            # 安卓：尝试用系统播放器打开（部分机型/目录可能无权限）
            self._process = subprocess.Popen(
                [
                    "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-t", "audio/mpeg",
                    "-d", f"file://{mp3_path}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            self._process = subprocess.Popen(
                ["afplay", mp3_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # Linux：优先 mpg123，否则 xdg-open
            player = "mpg123" if self._has("mpg123") else "xdg-open"
            self._process = subprocess.Popen(
                [player, mp3_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    @staticmethod
    def _has(cmd: str) -> bool:
        from shutil import which
        return which(cmd) is not None

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
        self._process = None
