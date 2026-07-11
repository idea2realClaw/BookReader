"""Base book reader interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class BookMetadata:
    title: str = "未知书名"
    author: str = "未知作者"
    cover_path: Optional[str] = None


class BookReader(ABC):
    def __init__(self, path: str):
        self.path = path
        self.metadata = BookMetadata()

    @abstractmethod
    def load(self) -> None:
        """Parse the book file."""
        pass

    @abstractmethod
    def get_page_count(self) -> int:
        pass

    @abstractmethod
    def get_page(self, index: int) -> str:
        """Return plain text content for page index."""
        pass

    def get_full_text(self) -> str:
        """Return the entire book text (used for window-based pagination).

        Default: join all logical pages. Subclasses may override to return
        the raw decoded text directly.
        """
        return "\n".join(self.get_page(i) for i in range(self.get_page_count()))
