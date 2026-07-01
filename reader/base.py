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
