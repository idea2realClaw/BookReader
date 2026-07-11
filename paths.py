"""跨平台应用数据目录解析。

桌面端：~/.bookreader/  （Windows: C:\\Users\\<user>\\.bookreader\\）
安卓端：Flet 运行时注入的 FLET_APP_STORAGE_DATA / FLET_APP_STORAGE_TEMP
        （指向 /data/data/<pkg>/files 或 /data/data/<pkg>/cache，app 私有可读写）

背景：在 Android 上 os.path.expanduser('~') 会返回 '/data'，导致 ~/.bookreader
被解析成 /data/.bookreader —— 根目录无权写，触发 PermissionError。
所以任何持久化文件都必须改走本模块的 app_data_dir()。
"""
import os
import sys


def app_data_dir() -> str:
    """返回 app 可读写的持久化数据目录（不带尾部斜杠）。

    优先级：
      1. FLET_APP_STORAGE_DATA  （Flet 安卓运行时注入的 app 私有 files 目录）
      2. FLET_APP_STORAGE_TEMP  （备用：app 私有 cache 目录）
      3. ~/.bookreader           （桌面：用户家目录下的 .bookreader）
    """
    for env_key in ("FLET_APP_STORAGE_DATA", "FLET_APP_STORAGE_TEMP"):
        d = os.getenv(env_key)
        if d:
            try:
                os.makedirs(d, exist_ok=True)
                if os.path.isdir(d):
                    return d
            except Exception:
                pass
    # 桌面端 fallback
    home = os.path.expanduser("~")
    base = os.path.join(home, ".bookreader")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return base


def app_data_path(filename: str) -> str:
    """返回 app 数据目录下某个文件的完整路径。"""
    return os.path.join(app_data_dir(), filename)
