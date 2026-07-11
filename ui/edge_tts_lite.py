"""
纯 Python 版 Edge TTS 合成客户端（无 aiohttp / multidict / frozenlist 依赖）。

为什么需要它：
- 官方 `edge_tts` 包顶层 import aiohttp，而 aiohttp 依赖的 multidict / frozenlist
  是 C 扩展，Flet 安卓包索引（pypi.flet.dev）未提供其安卓 wheel，导致
  `flet build apk` 失败、无法在安卓打包环境使用。
- 本模块仅依赖 `websockets`（纯 Python，可打包）+ `certifi`（纯 Python），
  完整复刻 edge_tts 的 WebSocket 合成协议（Sec-MS-GEC 令牌、SSML、二进制音频解析），
  因此安卓端也能真正使用 Edge TTS 的男/女声与倍速，而无需 pyjnius、无需第三方 APK。

协议细节摘自已安装的 edge_tts 源码（constants.py / drm.py / communicate.py），
仅把传输层从 aiohttp 换成 websockets，令牌与 SSML 逻辑保持一致。
"""

import asyncio
import hashlib
import secrets
import ssl
import time
import uuid
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

import websockets

# ---------------------------------------------------------------------------
# 常量（与 edge_tts 同步；如微软更新令牌版本，仅需调整 CHROMIUM_FULL_VERSION）
# ---------------------------------------------------------------------------
TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
BASE_URL = "speech.platform.bing.com/consumer/speech/synthesize/readaloud"
WSS_URL = f"wss://{BASE_URL}/edge/v1?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"

CHROMIUM_FULL_VERSION = "143.0.3650.75"
CHROMIUM_MAJOR_VERSION = CHROMIUM_FULL_VERSION.split(".", maxsplit=1)[0]
SEC_MS_GEC_VERSION = f"1-{CHROMIUM_FULL_VERSION}"

WIN_EPOCH = 11644473600  # 1601-01-01 与 1970-01-01 的秒差
S_TO_NS = 1e9

WSS_HEADERS = {
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        f" (KHTML, like Gecko) Chrome/{CHROMIUM_MAJOR_VERSION}.0.0.0 Safari/537.36"
        f" Edg/{CHROMIUM_MAJOR_VERSION}.0.0.0"
    ),
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# 令牌与头部
# ---------------------------------------------------------------------------
def _generate_sec_ms_gec() -> str:
    """生成 Sec-MS-GEC 令牌（与 edge_tts.drm.DRM.generate_sec_ms_gec 一致）。"""
    ticks = time.time()  # 时钟偏差校正本实现忽略（移动端通常已联网校时）
    ticks += WIN_EPOCH
    ticks -= ticks % 300  # 向下取整到 5 分钟
    ticks *= S_TO_NS / 100  # 转为 100 纳秒间隔（Windows file time）
    str_to_hash = f"{ticks:.0f}{TRUSTED_CLIENT_TOKEN}"
    return hashlib.sha256(str_to_hash.encode("ascii")).hexdigest().upper()


def _headers_with_muid() -> dict:
    headers = dict(WSS_HEADERS)
    assert "Cookie" not in headers
    headers["Cookie"] = f"muid={secrets.token_hex(16).upper()};"
    return headers


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ---------------------------------------------------------------------------
# 文本清洗与按字节长度切分（照搬 edge_tts.communicate）
# ---------------------------------------------------------------------------
def _remove_incompatible_characters(string) -> str:
    if isinstance(string, bytes):
        string = string.decode("utf-8")
    chars: List[str] = list(string)
    for idx, char in enumerate(chars):
        code = ord(char)
        if (0 <= code <= 8) or (11 <= code <= 12) or (14 <= code <= 31):
            chars[idx] = " "
    return "".join(chars)


def _find_last_newline_or_space_within_limit(text: bytes, limit: int) -> int:
    split_at = text.rfind(b"\n", 0, limit)
    if split_at < 0:
        split_at = text.rfind(b" ", 0, limit)
    return split_at


def _find_safe_utf8_split_point(text_segment: bytes) -> int:
    split_at = len(text_segment)
    while split_at > 0:
        try:
            text_segment[:split_at].decode("utf-8")
            return split_at
        except UnicodeDecodeError:
            split_at -= 1
    return split_at


def _adjust_split_point_for_xml_entity(text: bytes, split_at: int) -> int:
    while split_at > 0 and b"&" in text[:split_at]:
        ampersand_index = text.rindex(b"&", 0, split_at)
        if text.find(b";", ampersand_index, split_at) != -1:
            break
        split_at = ampersand_index
    return split_at


def _split_text_by_byte_length(text, byte_length: int):
    if isinstance(text, str):
        text = text.encode("utf-8")
    if byte_length <= 0:
        raise ValueError("byte_length must be greater than 0")
    while len(text) > byte_length:
        split_at = _find_last_newline_or_space_within_limit(text, byte_length)
        if split_at < 0:
            split_at = _find_safe_utf8_split_point(text)
        split_at = _adjust_split_point_for_xml_entity(text, split_at)
        if split_at < 0:
            raise ValueError("Maximum byte length is too small or invalid text")
        chunk = text[:split_at].strip()
        if chunk:
            yield chunk
        text = text[split_at if split_at > 0 else 1 :]
    remaining = text.strip()
    if remaining:
        yield remaining


# ---------------------------------------------------------------------------
# SSML 构造
# ---------------------------------------------------------------------------
def _mkssml(voice: str, rate: str, pitch: str, volume: str, escaped_text: str) -> str:
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
        f"<voice name='{voice}'>"
        f"<prosody pitch='{pitch}' rate='{rate}' volume='{volume}'>"
        f"{escaped_text}"
        "</prosody>"
        "</voice>"
        "</speak>"
    )


def _date_to_string() -> str:
    return time.strftime(
        "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime()
    )


def _ssml_headers_plus_data(request_id: str, timestamp: str, ssml: str) -> str:
    return (
        f"X-RequestId:{request_id}\r\n"
        "Content-Type:application/ssml+xml\r\n"
        f"X-Timestamp:{timestamp}Z\r\n"  # 非笔误，微软 Edge 的 bug
        "Path:ssml\r\n\r\n"
        f"{ssml}"
    )


def _get_headers_and_data(data: bytes, header_length: int) -> Tuple[dict, bytes]:
    headers = {}
    for line in data[:header_length].split(b"\r\n"):
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key] = value
    return headers, data[header_length + 2 :]


# ---------------------------------------------------------------------------
# 合成（核心）
# ---------------------------------------------------------------------------
async def synthesize(
    text: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
    out_path: Optional[str] = None,
) -> Optional[bytes]:
    """合成 text 为 Edge TTS 音频。成功返回 mp3 字节（并写入 out_path），失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return b""

    chunks = list(
        _split_text_by_byte_length(
            escape(_remove_incompatible_characters(text)), 4096
        )
    )

    ssl_ctx = _ssl_ctx()
    audio = bytearray()

    for partial in chunks:
        url = (
            f"{WSS_URL}&ConnectionId={uuid.uuid4().hex}"
            f"&Sec-MS-GEC={_generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
        )
        try:
            async with websockets.connect(
                url,
                additional_headers=_headers_with_muid(),
                ssl=ssl_ctx,
                max_size=None,
                open_timeout=15,
                close_timeout=15,
            ) as ws:
                # 1) speech.config
                await ws.send(
                    f"X-Timestamp:{_date_to_string()}\r\n"
                    "Content-Type:application/json; charset=utf-8\r\n"
                    "Path:speech.config\r\n\r\n"
                    '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                    '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
                    "},"
                    '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"'
                    "}}}}\r\n"
                )
                # 2) ssml
                await ws.send(
                    _ssml_headers_plus_data(
                        uuid.uuid4().hex,
                        _date_to_string(),
                        _mkssml(voice, rate, pitch, volume, partial.decode("utf-8")),
                    )
                )
                # 3) 读取响应
                audio_was_received = False
                async for received in ws:
                    if isinstance(received, str):
                        encoded = received.encode("utf-8")
                        params, _ = _get_headers_and_data(
                            encoded, encoded.find(b"\r\n\r\n")
                        )
                        path = params.get(b"Path")
                        if path == b"turn.end":
                            break
                        # audio.metadata / response / turn.start 忽略
                    else:  # bytes：二进制音频帧
                        if len(received) < 2:
                            continue
                        header_length = int.from_bytes(received[:2], "big")
                        if header_length > len(received):
                            continue
                        params, data = _get_headers_and_data(received, header_length)
                        if params.get(b"Path") != b"audio":
                            continue
                        content_type = params.get(b"Content-Type")
                        if content_type not in (b"audio/mpeg", None):
                            continue
                        if content_type is None and len(data) == 0:
                            continue
                        if len(data) == 0:
                            continue
                        audio.extend(data)
                        audio_was_received = True
                if not audio_was_received:
                    return None
        except Exception as ex:  # 单段失败即整体失败，交由调用方回退
            print(f"[EdgeLite] 合成段失败: {ex}")
            return None

    result = bytes(audio)
    if out_path and result:
        with open(out_path, "wb") as f:
            f.write(result)
    return result or None


def synthesize_sync(
    text: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
    out_path: Optional[str] = None,
) -> Optional[bytes]:
    """同步封装（供非 async 环境使用）。"""
    return asyncio.run(
        synthesize(text, voice, rate, pitch, volume, out_path)
    )
