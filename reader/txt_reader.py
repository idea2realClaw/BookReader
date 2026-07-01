import os
from typing import List
from .base import BookReader, BookMetadata


class TxtReader(BookReader):
    """Plain text reader, split into pages by a fixed character count."""

    PAGE_SIZE = 600

    def __init__(self, path: str):
        super().__init__(path)
        self.pages: List[str] = []

    def load(self) -> None:
        name = os.path.splitext(os.path.basename(self.path))[0]
        self.metadata = BookMetadata(title=name, author="")
        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
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
