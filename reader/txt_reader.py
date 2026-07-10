import os
from typing import List
from .base import BookReader, BookMetadata


def _decode_text(raw: bytes) -> str:
    """以 Unicode(UTF-8) 优先解码文本，避免中文 GBK 文件出现乱码。

    解码顺序：
    1. UTF-8（含 BOM，utf-8-sig）→ 绝大多数现代文本 / 跨平台文件
    2. GB18030（GBK 的超集，覆盖简繁中文及生僻字）→ 大量 Windows 中文 TXT
    3. 兜底：UTF-8 宽松模式，尽量保留可读内容
    """
    # 1) UTF-8（含 BOM）优先
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # 2) 常见中文编码（GBK / GB18030）
    try:
        return raw.decode("gb18030", errors="strict")
    except UnicodeDecodeError:
        pass
    # 3) 兜底：宽松解码，尽量保留内容
    return raw.decode("utf-8", errors="ignore")


class TxtReader(BookReader):
    """Plain text reader, split into pages by a fixed character count."""

    PAGE_SIZE = 600

    def __init__(self, path: str):
        super().__init__(path)
        self.pages: List[str] = []

    def load(self) -> None:
        name = os.path.splitext(os.path.basename(self.path))[0]
        self.metadata = BookMetadata(title=name, author="")
        # 以二进制读取后按编码解码，避免直接按 UTF-8 打开 GBK 中文文件产生乱码
        with open(self.path, "rb") as f:
            raw = f.read()
        text = _decode_text(raw)
        self.pages = self._split(text)

    def _split(self, text: str) -> List[str]:
        pages = []
        for i in range(0, len(text), self.PAGE_SIZE):
            pages.append(text[i : i + self.PAGE_SIZE])
        return pages or [""]

    def get_page_count(self) -> int:
        return len(self.pages)

    def get_page(self, index: int) -> str:
        return self.pages[index]
