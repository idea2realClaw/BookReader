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
import base64
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

# AudioState 枚举（COMPLETED 等），用于"单 Audio + COMPLETED 事件链"顺序播放。
try:
    from flet_audio.types import AudioState as _AudioState
except Exception:  # pragma: no cover
    _AudioState = None

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


def _tts_active_marker_path() -> str:
    """返回"TTS 正在连续朗读"标记文件路径。

    安卓端：Flet 注入的 FLET_APP_STORAGE_DATA（= /data/data/<pkg>/files），
    等价于原生 MainActivity 的 getFilesDir()；原生层轮询此文件判断是否
    需要启动 Foreground Service 保活。桌面端回退 ~/.bookreader/。"""
    for env_key in ("FLET_APP_STORAGE_DATA", "FLET_APP_STORAGE_TEMP"):
        d = os.getenv(env_key)
        if d and os.path.isdir(d):
            return os.path.join(d, ".tts_active")
    return os.path.join(os.path.expanduser("~"), ".bookreader", ".tts_active")


class TTSEngine:
    def __init__(self, page=None):
        self.page = page
        self._process = None
        self._httpd = None
        self.speed = 1.2        # 朗读倍速（1.0~2.0）
        self.voice = "male"     # 音色：male / female（缺省男）
        self._stop_event = None
        self._audio = None  # flet_audio.Audio 控件（安卓端应用内播放，懒创建）
        self._audio_just_registered = False  # 首次注册后给原生侧一点准备时间
        self._play_lock = asyncio.Lock()  # 防止并发播放同一 audio 控件
        self.on_play_start = None  # UI 回调：音频真正开始播放时调用（隐藏"Preparing..."）
        try:
            print(f"[TTS] 初始化：平台={'mobile' if self._is_mobile() else 'desktop'}，"
                  f"flet_audio={'可用' if _FTA is not None else '不可用(将回退系统播放器)'}")
        except Exception:
            pass

    # ---- 平台判断 ----
    def _is_mobile(self) -> bool:
        try:
            return bool(self.page.platform.is_mobile())
        except Exception:
            return False

    def _fire_play_start(self):
        """音频真正开始播放时触发 on_play_start 回调（UI 用它隐藏"Preparing..."）。
        回调可能调用 page.update()，由调用方在事件循环中执行，这里用 ensure_future
        兜底，避免在非事件循环上下文里直接 update 抛异常。幂等：重复调用无害。"""
        cb = self.on_play_start
        if cb is None:
            return
        try:
            res = cb()
            if asyncio.iscoroutine(res):
                asyncio.ensure_future(res)
        except Exception as ex:
            print(f"[TTS] on_play_start 回调异常(非致命): {ex}")

    def _voice_id(self, text: str) -> str:
        lang = _detect_lang(text)
        return VOICE_MAP.get(self.voice, VOICE_MAP["male"]).get(lang, VOICE_MAP["male"]["zh"])

    # ---- 临时目录（安卓需写到应用私有目录，保证可写可读、flet_audio 能读取）----
    def _mp3_temp_dir(self) -> str:
        """返回写 mp3 的临时目录。
        安卓端优先用 Flet 运行时注入的应用私有临时目录 FLET_APP_STORAGE_TEMP
        （必定可写可读，不受 scoped storage 限制，flet_audio/ExoPlayer 可正常读取）；
        其次退回 FLET_APP_STORAGE_DATA；再退回系统临时目录。桌面端用系统临时目录。"""
        if self._is_mobile():
            for env_key in ("FLET_APP_STORAGE_TEMP", "FLET_APP_STORAGE_DATA"):
                d = os.getenv(env_key)
                if d:
                    try:
                        os.makedirs(d, exist_ok=True)
                        if os.path.isdir(d):
                            return d
                    except Exception:
                        pass
        return tempfile.gettempdir()

    def _new_mp3_file(self):
        """在合适目录创建唯一 mp3 文件，返回 (fd, path)。移动端落到应用私有临时目录。"""
        return tempfile.mkstemp(suffix=".mp3", dir=self._mp3_temp_dir())

    # ---- 安卓防中断：TTS 活跃标记（驱动原生 Foreground Service）----
    def _tts_active_marker_path(self) -> str:
        """返回 TTS 活跃标记文件路径。

        安卓端：Flet 注入的 FLET_APP_STORAGE_DATA（=/data/data/<pkg>/files）
        与原生 MainActivity.getFilesDir() 完全等价 —— 原生层轮询此文件判断
        是否需要启动前台服务保活。桌面端回退 ~/.bookreader/。"""
        if self._is_mobile():
            for env_key in ("FLET_APP_STORAGE_DATA", "FLET_APP_STORAGE_TEMP"):
                d = os.getenv(env_key)
                if d:
                    try:
                        os.makedirs(d, exist_ok=True)
                        if os.path.isdir(d):
                            return os.path.join(d, ".tts_active")
                    except Exception:
                        pass
        base = os.path.join(os.path.expanduser("~"), ".bookreader")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        return os.path.join(base, ".tts_active")

    def _mark_tts_active(self):
        """标记 TTS 正在连续朗读（驱动原生 Foreground Service 保活）。"""
        try:
            p = self._tts_active_marker_path()
            with open(p, "w") as f:
                f.write("1")
        except Exception as ex:
            print(f"[TTS] 写活跃标记失败(非致命): {ex}")

    def _clear_tts_active(self):
        """清除 TTS 活跃标记（原生 Foreground Service 将自动停止）。"""
        try:
            p = self._tts_active_marker_path()
            if os.path.exists(p):
                os.remove(p)
        except Exception as ex:
            print(f"[TTS] 清除活跃标记失败(非致命): {ex}")

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
        # v1.0.40：Audio 对象没有 stop() 方法，用 pause() 停止播放。
        # ⚠️ 绝不能调 release()！release() 会把底层原生 player 释放掉，之后再次
        # play()（跨会话复用同一控件时）在 Android 上 setSourceBytes 抛异常 /
        # on_loaded 永不触发 → 第二遍朗读整段静音（v1.0.41 的毒药）。
        # 停止只 pause()，保持 player 存活；重启时直接换 src + play() 即可。
        try:
            await a.pause()
        except Exception:
            pass

    def _create_flet_audio(self, initial_src, on_loaded=None, on_state_change=None):
        """创建并注册一个全新的 flet_audio.Audio 控件（每段独立，绕开复用重载失效）。

        v1.0.42：复用同一个 Audio 控件、仅更新 src 时，真机上第 2 段起永远
        不触发 on_loaded（Flet 对超大 base64 字符串属性的 diff 不触发 dart 端
        重载）。改为每段新建独立控件——首段"创建 Audio + 注册 + 等 on_loaded"这条路
        在真机 100% 可靠出声，on_loaded 触发即证明控件已到达 dart 侧。"""
        if initial_src is None:
            raise ValueError("创建 Audio 必须传入 initial_src（mp3 base64 字符串）")
        kwargs = dict(
            src=initial_src,
            volume=1.0,
            autoplay=False,
            release_mode=_FTA.ReleaseMode.STOP,
        )
        if on_loaded is not None:
            kwargs["on_loaded"] = on_loaded
        if on_state_change is not None:
            kwargs["on_state_change"] = on_state_change
        audio = _FTA.Audio(**kwargs)
        try:
            self.page._services.register_service(audio)
            try:
                n = len(self.page._services._services)
                print(f"[TTS] flet_audio service 已注册 (registry size={n})")
            except Exception as diag_ex:
                print(f"[TTS] flet_audio service 已注册 (无法读取 registry size: {diag_ex})")
            try:
                print(f"[TTS] audio.page={audio.page is not None}, audio._i={getattr(audio, '_i', '?')}")
            except Exception:
                pass
        except Exception as ex:
            print(f"[TTS] 注册 flet_audio service 失败: {ex}")
            print("[TTS] 可能原因：pyproject.toml 缺少 [tool.flet.flutter.dependencies] flet_audio 声明")
        return audio

    async def _dispose_flet_audio(self):
        """销毁上一段的 Audio 控件，并【真正释放】底层原生 AudioPlayer。

        v1.0.42 及之前：只 pause()+release()+unregister_services()，但
        ServiceRegistry.unregister_services() 靠引用计数移除，registry 列表自身持有
        对旧 audio 的引用 → refcount 永远降不到阈值 → 旧 AudioService 永远不被移除、
        其 AudioPlayer 永远不被 dispose()。第 2 段的"新" AudioPlayer 与原生层残留的
        旧 player 抢 MediaPlayer 资源（audioplayers 在 Android 上对第二个 player 与残留
        player 冲突）→ setSourceBytes 抛异常 → loaded 事件不触发 → 静音。

        修复（v1.0.43）：除 release() 外，直接把旧 audio 从 registry._services 列表移除，
        再调 unregister_services() 兜底，强制 refcount 下降 → Flet 下发"移除控件" →
        dart 侧 AudioService.dispose() → player.dispose() 真正释放原生资源。这样下一段
        拿到的 AudioPlayer 是干净的全新实例，setSourceBytes 才能成功。"""
        a = self._audio
        if a is None:
            return
        try:
            await a.pause()
        except Exception:
            pass
        try:
            await a.release()
        except Exception:
            pass
        self._audio = None
        try:
            reg = self.page._services
            svcs = getattr(reg, "_services", None)
            if svcs is not None and a in svcs:
                svcs.remove(a)
                try:
                    reg.update()  # 触发 diff → dart 侧 dispose 旧 AudioService → player.dispose()
                except Exception:
                    pass
            try:
                reg.unregister_services()  # 兜底（此时 refcount 已因移除而下降）
            except Exception:
                pass
            try:
                n = len(getattr(reg, "_services", []))
                print(f"[TTS] 已 dispose 旧 Audio：registry size={n}")
            except Exception:
                pass
        except Exception as ex:
            print(f"[TTS] dispose 移除 registry 失败(非致命): {ex}")

    def _get_flet_audio(self, initial_src=None, on_loaded=None, on_state_change=None):
        """懒创建并注册一个 flet_audio.Audio 控件（应用内播放，原生支持 Android）。
        返回 audio。首次创建后需给原生控件一点注册时间再播放。

        关键坑 1（Flet 0.85.3 Service 注册）：Audio 是 Service 子类，其 init() 会调用
        context.page._services.register_service(self) 来注册到原生侧。但 init() 在
        __post_init__ 时执行，若不在 Flet 事件上下文里（如在后台 asyncio task 中创建），
        context.page 会抛 RuntimeError 被静默吞掉 → service 永远不会注册到原生侧。
        修复：手动调用 page._services.register_service(audio) 注册。

        关键坑 2（flet_audio dart 端 src 必须非空）：
        flet_audio 的 dart 端 AudioService.init() 会调用 update()，update() 检查 src，
        src 为空时抛异常 "Audio must have 'src' specified." → AudioService 初始化失败
        → 后续 audio.update() / play() 都不会被执行 → 30秒超时。
        修复：创建 Audio 时必须传非空 src。

        关键坑 3（v1.0.36-1.0.39：原始 bytes 更新不可靠）：
        flet_audio.Audio.src 类型是 Optional[Union[str, bytes]]，支持三种格式：
        - URL 或本地 asset 文件路径（str）
        - base64 字符串
        - 原始字节数据（bytes）
        dart 端 _applySource() 对路径会调用 setSourceDeviceFile(path)，对 bytes 会调用
        setSourceBytes(bytes)。
        
        **Android 上 setSourceDeviceFile 会抛 PlatformException**：
        "Failed to set source. MEDIA_ERROR_UNKNOWN {what:1}, MEDIA_ERROR_SYSTEM"
        原因可能是 Android 11+ scoped storage 限制、MediaPlayer 路径解析 bug、或
        app cache 目录权限问题。具体根因不明，但用 bytes 模式可以完全绕过这些问题。
        
        **v1.0.39 日志发现：Audio 对象没有 stop() 方法**，所以 v1.0.39 的 stop() 调用全部
        无效。同时发现复用 Audio 对象更新 audio.src = new_bytes 后 dart 端不再触发 on_loaded，
        推断是 Flet 的 Prop 变更检测对 bytes 不可靠（或 update 补丁未实际发送新 src）。
        
        修复（v1.0.40）：把 mp3 bytes 先转为 base64 字符串，再用字符串作为 src。Flet 对
        字符串的变更检测可靠，dart 端 getSrc() 会把 base64 字符串解码回 bytes 并调用
        setSourceBytes。每段 base64 内容不同，保证 src 变更被识别，player 会重新加载。

        关键坑 4（on_loaded 事件可能在设置回调之前触发）：
        register_service 可能把 audio 控件立即发送到原生侧，dart 端 init() → _applySource()
        可能在 Python 端设置 on_loaded 回调之前就完成。所以 on_loaded 回调必须在创建 Audio
        时就传入（通过 Audio.__init__ 的 on_loaded 参数），不能在创建后再设置。"""
        if self._audio is None:
            if initial_src is None:
                raise ValueError("首次创建 Audio 必须传入 initial_src（mp3 base64 字符串）")
            # 创建 Audio 时直接用 mp3 base64 字符串（dart 端解码为 bytes 后 setSourceBytes）
            # on_loaded 回调必须在创建时就传入，避免错过 dart 端 init() 触发的事件
            kwargs = dict(
                src=initial_src,
                volume=1.0,
                autoplay=False,
                release_mode=_FTA.ReleaseMode.STOP,
            )
            if on_loaded is not None:
                kwargs["on_loaded"] = on_loaded
            if on_state_change is not None:
                kwargs["on_state_change"] = on_state_change
            self._audio = _FTA.Audio(**kwargs)
            try:
                # 正确注册方式：通过 page._services.register_service()
                # ServiceRegistry 会把 _services 列表（含 audio）序列化发送到原生侧
                self.page._services.register_service(self._audio)
                self._audio_just_registered = True
                # 诊断：确认 service 真的注册到 registry 里（注意是 _services._services）
                try:
                    n = len(self.page._services._services)
                    print(f"[TTS] flet_audio service 已注册 (registry size={n})")
                except Exception as diag_ex:
                    print(f"[TTS] flet_audio service 已注册 (无法读取 registry size: {diag_ex})")
                # 诊断：确认 audio 控件的 page 引用和 control ID
                try:
                    print(f"[TTS] audio.page={self._audio.page is not None}, audio._i={getattr(self._audio, '_i', '?')}")
                except Exception:
                    pass
            except Exception as ex:
                print(f"[TTS] 注册 flet_audio service 失败: {ex}")
                print("[TTS] 可能原因：pyproject.toml 缺少 [tool.flet.flutter.dependencies] flet_audio 声明")
                self._audio_just_registered = False
        return self._audio

    async def _wait_for_audio_loaded(self, audio, timeout: float = 5.0) -> bool:
        """等待 audio 控件的 on_loaded 事件触发（原生侧 _applySource 完成）。
        返回 True 表示已加载，False 表示超时。"""
        loop = asyncio.get_event_loop()
        loaded_future = loop.create_future()

        def _on_loaded(e):
            if not loaded_future.done():
                loaded_future.set_result(True)

        audio.on_loaded = _on_loaded
        try:
            await asyncio.wait_for(loaded_future, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            # 清理回调，避免重复触发
            audio.on_loaded = None

    async def _play_flet_audio(self, mp3_path: str, duration: float, stop_event):
        """用 flet_audio 播放本地 mp3 文件，等待播放结束（或停止信号）。

        v1.0.40 关键修复：把 mp3 bytes 转为 base64 字符串作为 src。
        原因：v1.0.36-1.0.39 用原始 bytes 作为 src，复用 Audio 对象时更新 src 不触发
        dart 端 on_loaded 事件，导致后续段一直播放旧音频。Flet 对字符串的变更检测
        更可靠，base64 字符串内容不同，update() 补丁一定会把新 src 发送到 dart 端，
        dart 端解码为 bytes 后调用 setSourceBytes，触发 on_loaded 并播放新音频。
        """
        try:
            size = os.path.getsize(mp3_path) if os.path.exists(mp3_path) else -1
        except Exception:
            size = -1
        print(f"[TTS] flet_audio 播放: {mp3_path} (size={size})")

        # 读取 mp3 文件为 bytes，然后转为 base64 字符串（v1.0.40：用字符串触发可靠变更检测）
        try:
            with open(mp3_path, 'rb') as f:
                mp3_bytes = f.read()
            mp3_b64 = base64.b64encode(mp3_bytes).decode('ascii')
            print(f"[TTS] 读取 mp3 bytes: {len(mp3_bytes)} bytes, base64 长度: {len(mp3_b64)}")
            # 诊断：打印前 16 字节 hash，确认不同段内容不同
            print(f"[TTS] mp3 前 16 字节 hash: {hash(mp3_bytes[:16])}")
        except Exception as ex:
            print(f"[TTS] 读取 mp3 文件失败: {ex}")
            raise

        # v1.0.42：每段都销毁上一段的旧 Audio，再新建一个独立控件。
        # 复用控件重载在真机失效（Flet 对超大 base64 字符串 diff 不触发 dart 重载）。
        await self._dispose_flet_audio()
        # 等 dart 侧把旧 AudioService/AudioPlayer 真正 dispose() 完（异步），
        # 否则下一段的新 player 可能与残留的旧 player 在原生层短暂冲突。
        await asyncio.sleep(0.3)

        # 创建 on_loaded future（必须在创建/更新 audio 之前设置回调）
        # 原因：register_service 可能把 audio 立即发送到原生侧，dart 端 init() → _applySource()
        # 可能在 Python 端设置 on_loaded 回调之前就完成，导致事件丢失。
        loop = asyncio.get_event_loop()
        loaded_future = loop.create_future()

        def _on_loaded(e):
            print(f"[TTS] audio on_loaded 事件触发")
            if not loaded_future.done():
                loaded_future.set_result(True)

        # 监听播放状态变化（诊断用）
        state_log = []
        def _on_state_change(e):
            try:
                state = e.data if hasattr(e, 'data') else '?'
            except Exception:
                state = '?'
            state_log.append(state)
            print(f"[TTS] audio on_state_change: {state}")

        # 每段都新建一个独立的 Audio 控件（"首段方法"，真机 100% 可靠出声）。
        # on_loaded 触发即证明控件已到达 dart 侧，绝不会出现 inexistent control。
        audio = self._create_flet_audio(
            initial_src=mp3_b64,  # ← base64 字符串模式，dart 端解码为 bytes → setSourceBytes
            on_loaded=_on_loaded,
            on_state_change=_on_state_change,
        )
        self._audio = audio
        # 原生 Audio service 首次注册需要一点时间，否则首句可能无声
        await asyncio.sleep(0.5)
        print(f"[TTS] 新建 Audio（每段独立控件），base64 长度 {len(mp3_b64)} 字符")
        try:
            audio.update()
        except Exception as ex:
            print(f"[TTS] audio.update() 异常: {ex}")

        # 等待 on_loaded 事件（原生 _applySource 完成后触发），最多等 8 秒
        # on_loaded 触发即证明控件已到达 dart 侧；超时则重试一次 update
        try:
            await asyncio.wait_for(loaded_future, timeout=8.0)
            print("[TTS] 音频已加载（on_loaded 触发）")
        except asyncio.TimeoutError:
            # 偶发：控件已注册但 dart 端尚未完成 setSourceBytes，重试一次 update
            print("[TTS] 警告：等待音频加载超时(8s)，重试 update 一次")
            try:
                audio.src = mp3_b64
                audio.update()
            except Exception as ex:
                print(f"[TTS] 重试 update 异常: {ex}")
            try:
                await asyncio.wait_for(loaded_future, timeout=5.0)
                print("[TTS] 重试后音频已加载（on_loaded 触发）")
            except asyncio.TimeoutError:
                print("[TTS] 警告：重试后仍超时，仍尝试播放")
                print("[TTS] 可能原因：1) mp3 base64 损坏；2) 原生 audioplayers setSourceBytes 失败；3) dart 端 _applySource 异常")
                await asyncio.sleep(0.3)
        finally:
            # 清理 on_loaded 回调，避免重复触发
            try:
                audio.on_loaded = None
            except Exception:
                pass

        if stop_event.is_set():
            return

        try:
            await audio.play()
            self._fire_play_start()  # 音频已开始播放 → 隐藏 Preparing...
            print("[TTS] audio.play() 已调用（未抛异常）")
        except Exception as ex:
            print(f"[TTS] flet_audio.play() 抛出异常: {ex}")
            raise
        # 诊断：播放 0.4s 后检查是否真的在播（位置应 > 0）；否则给出明确告警
        try:
            await asyncio.sleep(0.4)
            pos = await audio.get_current_position()
            pos_ms = pos.in_milliseconds if (pos and hasattr(pos, 'in_milliseconds')) else 0
            print(f"[TTS] flet_audio 播放中 position={pos_ms}ms, state_log={state_log}")
            if pos_ms == 0:
                print("[TTS] 警告：play() 已调用但播放位置仍为 0，可能无声")
                print("[TTS] 可能原因：1) mp3 文件损坏或路径不可达；2) 原生 audioplayers 初始化失败；3) audio_player 处于 error 状态")
        except Exception as ex:
            print(f"[TTS] 读取播放位置失败(非致命): {ex}")
        step = 0.1
        elapsed = 0.0
        limit = duration + 2.0  # 给真实播放一点余量，避免提前切断尾音
        while elapsed < limit and not stop_event.is_set():
            await asyncio.sleep(step)
            elapsed += step
        # v1.0.40：每段结束用 pause() + release() 重置 player（Audio 没有 stop() 方法）
        try:
            await audio.pause()
            await audio.release()
            print("[TTS] 播放结束：已 pause() + release() 重置 player（保持 AudioPlayer 实例可用）")
        except Exception:
            pass
        # 清理状态监听
        try:
            audio.on_state_change = None
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
        fd, mp3_path = self._new_mp3_file()
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

    async def synthesize_to_path_named(self, text: str, path: str) -> Optional[str]:
        """合成 text 并写入指定 path（覆盖写），返回 path；失败返回 None。
        用于 ping-pong 双缓冲方案（固定文件名 tmpbookreader1/2.mp3）。"""
        text = (text or "").strip()
        if not text:
            return None
        # 优先 Edge TTS
        if _edge_lite_synthesize is not None:
            try:
                mp3 = await _edge_lite_synthesize(
                    text, self._voice_id(text), _rate_string(self.speed)
                )
                if mp3:
                    try:
                        with open(path, "wb") as f:
                            f.write(mp3)
                        return path
                    except Exception as ex:
                        print(f"[TTS] 写入指定路径失败: {ex}")
                        return None
            except Exception as ex:
                print(f"[TTS] Edge 合成失败，回退 gTTS: {ex}")
        # 回退 gTTS（写到指定路径）
        if _GTTS is not None:
            try:
                lang = "zh-cn" if _CJK_RE.search(text) else "en"
                await asyncio.to_thread(_GTTS(text=text, lang=lang, tld="com").save, path)
                if os.path.exists(path):
                    return path
            except Exception as ex:
                print(f"[TTS] gTTS 写入指定路径失败: {ex}")
        return None

    # ==================================================================
    # 整本连续朗读（v1.0.44）：只用一个 AudioPlayer 播完整场
    # ==================================================================
    async def _synthesize_bytes(self, text: str) -> Optional[bytes]:
        """合成 text 为 mp3 字节（优先 Edge TTS，失败回退 gTTS）。"""
        text = (text or "").strip()
        if not text:
            return None
        if _edge_lite_synthesize is not None:
            try:
                mp3 = await _edge_lite_synthesize(
                    text, self._voice_id(text), _rate_string(self.speed)
                )
                if mp3:
                    return mp3
            except Exception as ex:
                print(f"[TTS] Edge 合成失败，回退 gTTS: {ex}")
        if _GTTS is not None:
            try:
                fd, tmp = self._new_mp3_file()
                os.close(fd)
                lang = "zh-cn" if _CJK_RE.search(text) else "en"
                await asyncio.to_thread(
                    _GTTS(text=text, lang=lang, tld="com").save, tmp
                )
                if os.path.exists(tmp):
                    with open(tmp, "rb") as f:
                        data = f.read()
                    os.unlink(tmp)
                    return data
            except Exception as ex:
                print(f"[TTS] gTTS 合成失败: {ex}")
        return None

    async def synthesize_concat(self, segments: list, out_path: str) -> Optional[str]:
        """把多个文本段分别用 Edge TTS 合成，流式拼接写入 out_path（一个完整 mp3）。

        用于"整本连续朗读"：全程只创建一个 AudioPlayer（首段可靠路径），
        绕开 flet_audio 在安卓上"第二个 player 与原生残留资源冲突 → on_loaded
        永不触发 → 静音"的坑。返回 out_path；全部合成失败返回 None。

        说明：Edge TTS 同一语音的 MP3 帧参数一致，逐句字节拼接在 ExoPlayer/
        audioplayers 下可正常连续播放（句边界仅有极轻微静默，语音场景不可闻）。"""
        ok = False
        try:
            with open(out_path, "wb") as f:
                for seg in segments:
                    seg = (seg or "").strip()
                    if not seg:
                        continue
                    try:
                        mp3 = await self._synthesize_bytes(seg)
                        if mp3:
                            f.write(mp3)
                            ok = True
                    except Exception as ex:
                        print(f"[TTS] 拼接合成单段失败(跳过): {ex}")
        except Exception as ex:
            print(f"[TTS] 写入拼接 mp3 失败: {ex}")
            return None
        return out_path if ok else None

    async def _create_and_load(self, mp3_path: str):
        """创建【单个】flet_audio.Audio（首段可靠路径），等 on_loaded 返回 audio。

        用于"整本连续朗读"：全程只此一个 AudioPlayer，彻底绕开
        flet_audio 在安卓上"第二个 player 与原生残留资源冲突 → on_loaded 永不触发
        → 静音"。返回 audio；失败返回 None。"""
        try:
            size = os.path.getsize(mp3_path) if os.path.exists(mp3_path) else -1
        except Exception:
            size = -1
        print(f"[TTS] 连续朗读加载: {mp3_path} (size={size})")
        try:
            with open(mp3_path, "rb") as f:
                mp3_bytes = f.read()
            mp3_b64 = base64.b64encode(mp3_bytes).decode("ascii")
            print(f"[TTS] 连续朗读 mp3 bytes={len(mp3_bytes)}, base64 长度={len(mp3_b64)}")
            print(f"[TTS] mp3 前 16 字节 hash: {hash(mp3_bytes[:16])}")
        except Exception as ex:
            print(f"[TTS] 读取连续朗读 mp3 失败: {ex}")
            return None

        loop = asyncio.get_event_loop()
        loaded_future = loop.create_future()

        def _on_loaded(e):
            print("[TTS] audio on_loaded 事件触发（连续朗读）")
            if not loaded_future.done():
                loaded_future.set_result(True)

        state_log = []

        def _on_state_change(e):
            try:
                state = e.data if hasattr(e, "data") else "?"
            except Exception:
                state = "?"
            state_log.append(state)

        audio = self._create_flet_audio(
            initial_src=mp3_b64,
            on_loaded=_on_loaded,
            on_state_change=_on_state_change,
        )
        self._audio = audio
        await asyncio.sleep(0.5)
        try:
            audio.update()
        except Exception as ex:
            print(f"[TTS] 连续朗读 audio.update() 异常: {ex}")
        try:
            await asyncio.wait_for(loaded_future, timeout=15.0)
            print("[TTS] 连续朗读音频已加载（on_loaded 触发）")
        except asyncio.TimeoutError:
            print("[TTS] 警告：连续朗读音频加载超时(15s)，仍尝试播放")
        return audio

    async def play_continuous_mp3(self, mp3_path: str, duration: float, stop_event):
        """整本连续朗读：只创建【一个】AudioPlayer（首段可靠路径）播放整段 mp3 一次，
        彻底绕开 flet_audio 在安卓上"第二个 player 与原生残留资源冲突 → on_loaded
        永不触发 → 静音"。调用方负责在播放期间用计时驱动高亮；本方法只管
        "播放到结束或停止信号"。"""
        if not self._is_mobile():
            d = duration if duration and duration > 0 else _estimate_duration("")
            await self._play_pygame(mp3_path, stop_event, d)
            return
        await self._dispose_flet_audio()  # 确保开始时干净（首次为 None）
        audio = await self._create_and_load(mp3_path)
        if audio is None:
            print("[TTS] 连续朗读 Audio 创建/加载失败，回退静默计时")
            await self._wait(duration, stop_event)
            return
        try:
            if stop_event.is_set():
                return
            await audio.play()
            self._fire_play_start()  # 音频已开始播放 → 隐藏 Preparing...
            print("[TTS] 连续朗读 audio.play() 已调用（未抛异常）")
            step = 0.2
            elapsed = 0.0
            limit = duration + 3.0  # 给真实播放一点余量，避免提前切断尾音
            while elapsed < limit and not stop_event.is_set():
                await asyncio.sleep(step)
                elapsed += step
        finally:
            try:
                await audio.pause()
                await audio.release()
                print("[TTS] 连续朗读结束：已 pause() + release()（全程单个 player）")
            except Exception:
                pass
            self._audio = None

    # ==================================================================
    # 单 Audio + COMPLETED 事件链顺序播放（v1.0.45，按师父架构）
    # 不用 release（ExoPlayer 自行处理换源），不用硬等 on_loaded
    # （用 COMPLETED 链驱动）。边播边转，零整本预处理延迟。
    # ==================================================================
    async def play_sequential(self, segments, stop_event, on_seg_start=None):
        """单 flet_audio.Audio 控件 + COMPLETED 事件链驱动顺序播放。

        架构（师父指定）：
        - 页面【只创建一个】Audio 控件；切歌时改 src 并 play()，
          避免重复实例化丢失状态。
        - 监听 on_state_change 的 COMPLETED 事件来驱动下一首（play_next），
          切勿用 time.sleep / for 循环硬等。
        - 复用同一 Audio 控件【不手动 release】（ExoPlayer 会处理换源）。

        实测结论：v1.0.41 的毒药是切歌前调了 pause()+release()，
        把 player 撕碎后 setSourceBytes 在 Android 抛异常 → on_loaded 永不触发。
        本方法去掉 release，仅 audio.src = 新base64 + update() + play()。

        segments：句子文本列表（每段一句）。on_seg_start(idx, text) 可选回调，
        在每段开始播放时调用（UI 高亮 + 翻页）。"""
        if not segments:
            return
        # 桌面端：逐段 pygame（无 player 冲突），直接逐句播
        if not self._is_mobile():
            for i, s in enumerate(segments):
                if stop_event.is_set():
                    break
                if on_seg_start is not None:
                    try:
                        on_seg_start(i, s)
                    except Exception:
                        pass
                await self._speak_edge(s, stop_event)
            return

        # ---- 移动端：单 Audio + COMPLETED 事件链 ----
        # 持久单 Audio 控件（v1.1.3 修复"停止后再启动没声音"）：
        # 整个阅读器生命周期只创建一个 Audio 控件，跨会话【绝不 dispose /
        # 绝不 release】。停止只 pause()，重启直接复用旧控件换 src + play()。
        # 根因：Android 上 flet_audio 的 AudioplayersPlugin 是单例，
        # dispose/recreate 第二个 Audio 后原生侧拿不到干净 player →
        # on_loaded 永不触发、play() TimeoutException（v1.0.34~v1.0.45 反复踩的坑）。
        # 而段内本来就是"换 src + play()"且已验证可靠，跨会话复用同一机制即可。
        loop = asyncio.get_event_loop()
        loaded_future = loop.create_future()
        completed_holder = [loop.create_future()]  # 当前段播完置位

        def _b64_of(p):
            with open(p, "rb") as f:
                data = f.read()
            return base64.b64encode(data).decode("ascii"), hash(data[:16])

        def _on_loaded(e):
            print("[TTS] audio on_loaded 触发（顺序播放）")
            if not loaded_future.done():
                loaded_future.set_result(True)

        def _on_state(e):
            st = getattr(e, "state", None)
            if st is None:
                st = getattr(e, "data", None)
            print(f"[TTS] audio on_state_change: {st}")
            is_completed = (st == "completed") or (
                _AudioState is not None and st == _AudioState.COMPLETED
            )
            if is_completed:
                if not completed_holder[0].done():
                    completed_holder[0].set_result(True)

        # 先合成第 0 段（创建 Audio 必须非空 src）
        mp3_0 = await self._synthesize_mobile_to_file(segments[0])
        if mp3_0 is None:
            print("[TTS] 顺序播放：首段合成失败，回退静默计时")
            for s in segments:
                if stop_event.is_set():
                    break
                await self._wait(_estimate_duration(s), stop_event)
            return
        b64_0, hash_0 = _b64_of(mp3_0)
        try:
            os.unlink(mp3_0)
        except Exception:
            pass

        # 复用持久 Audio 控件：若上一会话已创建且仍挂在页面上，直接复用
        # （重设回调 + 首段 src，底层 player 始终存活）；否则（首次）创建【单个】Audio。
        # 两者都不 release / 不 dispose。
        if self._audio is not None and getattr(self._audio, "page", None) is not None:
            audio = self._audio
            audio.on_loaded = _on_loaded
            audio.on_state_change = _on_state
            audio.src = b64_0
            print(f"[TTS] 顺序播放：复用【持久】Audio（id={getattr(audio, '_i', '?')}），"
                  f"首段 base64={len(b64_0)} 字符, hash={hash_0}")
        else:
            audio = self._create_flet_audio(
                initial_src=b64_0,
                on_loaded=_on_loaded,
                on_state_change=_on_state,
            )
            self._audio = audio
            print(f"[TTS] 顺序播放：创建【单】Audio，首段 base64={len(b64_0)} 字符, "
                  f"hash={hash_0}")
        await asyncio.sleep(0.5)  # 原生注册缓冲
        try:
            audio.update()
        except Exception as ex:
            print(f"[TTS] audio.update() 异常: {ex}")

        # 等首段加载（最多 8s；即使 on_loaded 没到也尝试播）
        try:
            await asyncio.wait_for(loaded_future, timeout=8.0)
            print("[TTS] 顺序播放：首段已加载")
        except asyncio.TimeoutError:
            print("[TTS] 警告：首段加载超时(8s)，仍尝试播放")

        if stop_event.is_set():
            return

        if on_seg_start is not None:
            try:
                on_seg_start(0, segments[0])
            except Exception as ex:
                print(f"[BookViewer] on_seg_start 回调异常(非致命): {ex}")

        try:
            await audio.play()
            self._fire_play_start()  # 音频已开始播放 → 隐藏 Preparing...
            print("[TTS] 顺序播放：audio.play()(段0) 已调用")
        except Exception as ex:
            print(f"[TTS] 段0 audio.play() 异常: {ex}")
            return

        # 预合成第 1 段（段0 播放期间并行，消除段间间隙）
        next_task = None
        if len(segments) > 1:
            next_task = asyncio.create_task(
                self._synthesize_mobile_to_file(segments[1])
            )

        # 事件链主循环：COMPLETED → 合成下一段 → 换 src → play()
        idx = 0
        while idx < len(segments) - 1 and not stop_event.is_set():
            completed_holder[0] = loop.create_future()
            try:
                await asyncio.wait_for(
                    completed_holder[0],
                    timeout=_estimate_duration(segments[idx]) + 30.0,
                )
            except asyncio.TimeoutError:
                print(f"[TTS] 警告：段{idx} 未在预期内 COMPLETED，尝试继续")
            if stop_event.is_set():
                break
            nxt = idx + 1
            if nxt >= len(segments):
                break
            # 取预合成好的下一段（通常段0 播放期间已完成）
            mp3_next = None
            if next_task is not None:
                try:
                    mp3_next = await next_task
                except Exception as ex:
                    print(f"[TTS] 预合成段{nxt} 失败: {ex}")
            if mp3_next is None:
                mp3_next = await self._synthesize_mobile_to_file(segments[nxt])
            if mp3_next is None:
                print(f"[TTS] 段{nxt} 合成失败，静默跳过")
                idx = nxt
                continue
            b64_next, hash_next = _b64_of(mp3_next)
            try:
                os.unlink(mp3_next)
            except Exception:
                pass

            # ★ 关键：不 release，直接换 src + play()（ExoPlayer 处理换源）
            audio.src = b64_next
            audio.update()
            print(f"[TTS] 顺序播放：换 src 播段{nxt}，base64={len(b64_next)} 字符, hash={hash_next}")

            if on_seg_start is not None:
                try:
                    on_seg_start(nxt, segments[nxt])
                except Exception as ex:
                    print(f"[BookViewer] on_seg_start 回调异常(非致命): {ex}")

            try:
                await audio.play()
                self._fire_play_start()  # 音频已开始播放 → 隐藏 Preparing...
                print(f"[TTS] 顺序播放：audio.play()(段{nxt}) 已调用")
            except Exception as ex:
                print(f"[TTS] 段{nxt} audio.play() 异常: {ex}")
                break

            # 诊断：0.5s 后检查是否真在播（position>0 = 换源成功出声）
            try:
                await asyncio.sleep(0.5)
                pos = await audio.get_current_position()
                pos_ms = pos.in_milliseconds if (pos and hasattr(pos, "in_milliseconds")) else 0
                print(f"[TTS] 顺序播放：段{nxt} 播放中 position={pos_ms}ms "
                      f"({'出声OK' if pos_ms > 0 else '警告：position=0 可能无声'})")
            except Exception as ex:
                print(f"[TTS] 读取段{nxt} 播放位置失败(非致命): {ex}")

            # 预合成下下一段
            nxt2 = nxt + 1
            next_task = asyncio.create_task(
                self._synthesize_mobile_to_file(segments[nxt2])
            ) if nxt2 < len(segments) else None
            idx = nxt

        # 收尾：暂停（不 release，按用户架构；页面 on_unmount 时再 release）
        try:
            await audio.pause()
            print("[TTS] 顺序播放结束：已 pause()（未 release，单 Audio 复用）")
        except Exception:
            pass

    async def speak_file(self, mp3_path: str, stop_event,
                        duration: Optional[float] = None) -> float:
        """直接播放已合成好的 mp3 文件（每段都新建独立 Audio 控件，可靠出声）。

        桌面端：直接用 pygame 播放该文件（不经过 flet_audio）。"""
        if mp3_path is None or not os.path.exists(mp3_path):
            print(f"[TTS] speak_file 收到无效 mp3 路径: {mp3_path}")
            return 0.0
        if not self._is_mobile():
            d = duration if duration is not None else _estimate_duration("")
            await self._play_pygame(mp3_path, stop_event, d)
            return d
        d = duration if duration is not None else _estimate_duration("")
        async with self._play_lock:
            try:
                await self._play_flet_audio(mp3_path, d, stop_event)
            except Exception as ex:
                print(f"[TTS] flet_audio 播放失败，回退系统播放器(file://): {ex}")
                try:
                    self._play_via_file_uri(mp3_path)
                    await self._wait(d, stop_event)
                finally:
                    self._shutdown_server()
        return d

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
                self._fire_play_start()  # 音频已开始播放 → 隐藏 Preparing...
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
        回退到本地文件 file:// + 系统播放器（避开 HTTP 的 cleartext 限制）。
        prefetched_path 为预取好的 mp3 文件，传给它可跳过联网合成、实现翻页无缝衔接。"""
        duration = _estimate_duration(text)
        print(f"[TTS] 安卓播放：flet_audio={'可用' if _FTA is not None else '不可用→回退系统播放器(file://)'}")
        mp3 = prefetched_path if (prefetched_path and os.path.exists(prefetched_path)) \
            else await self._synthesize_mobile_to_file(text)
        if mp3 is None:
            await self._wait(duration, stop_event)
            return duration
        # 优先用 flet_audio 应用内播放（可靠出声）；缺失则回退本地文件播放器
        if _FTA is not None:
            # 用锁防止多个 speak() 并发调用同一 audio 控件（会导致 src 被覆盖、
            # play() 在错误的 source 上执行、原生侧状态混乱）
            async with self._play_lock:
                try:
                    await self._play_flet_audio(mp3, duration, stop_event)
                except Exception as ex:
                    print(f"[TTS] flet_audio 播放失败，回退系统播放器(file://): {ex}")
                    try:
                        self._play_via_file_uri(mp3)
                        await self._wait(duration, stop_event)
                    finally:
                        self._shutdown_server()
        else:
            try:
                self._play_via_file_uri(mp3)
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
                    fd, path = self._new_mp3_file()
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
            fd, mp3_path = self._new_mp3_file()
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

    def _android_public_path(self, mp3_path: str) -> str:
        """把一个 app 私有 mp3 复制到一个系统播放器（不同 UID）也能读到的位置，
        返回该副本的本地路径。优先 /sdcard/BookReader（部分 ROM 可读写），
        失败则退回原路径。复制副本是为了绕开 scoped storage 对 app 私有文件的跨应用读取限制。"""
        base = os.environ.get("EXTERNAL_STORAGE") or "/sdcard"
        dst_dir = os.path.join(base, "BookReader")
        try:
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, os.path.basename(mp3_path))
            with open(mp3_path, "rb") as src_f, open(dst, "wb") as dst_f:
                dst_f.write(src_f.read())
            try:
                os.chmod(dst, 0o644)
            except Exception:
                pass
            return dst
        except Exception as ex:
            print(f"[TTS] 复制到公共目录失败，直接用原路径: {ex}")
            return mp3_path

    def _play_via_file_uri(self, mp3_path: str):
        """回退方案：把 mp3 放到系统播放器可读的位置，用 file:// URI 拉起系统播放器。
        与 _play_via_local_server 的区别：不经过 HTTP/127.0.0.1，避免 Android 9+ 默认
        禁止 cleartext 导致系统播放器拉不到音频而静默失败。"""
        public = self._android_public_path(mp3_path)
        uri = "file://" + public
        try:
            self._process = subprocess.Popen(
                [
                    "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-t", "audio/mpeg",
                    "-d", uri,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[TTS] 安卓播放 file:// URI: {uri}")
        except Exception as ex:
            print(f"[TTS] 启动系统播放器(file://)失败: {ex}")

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
