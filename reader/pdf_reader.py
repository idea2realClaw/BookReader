import os
from pypdf import PdfReader as PyPdfReader
from .base import BookReader, BookMetadata


class PdfReader(BookReader):
    """PDF reader using pure-Python pypdf."""

    def __init__(self, path: str):
        super().__init__(path)
        self._doc = None

    def load(self) -> None:
        self._doc = PyPdfReader(self.path)
        title = os.path.splitext(os.path.basename(self.path))[0]
        # Try to extract title from metadata.
        meta = self._doc.metadata
        if meta and getattr(meta, "title", None):
            title = str(meta.title)
        self.metadata = BookMetadata(title=title, author="")

    def get_page_count(self) -> int:
        return len(self._doc.pages)

    def get_page(self, index: int) -> str:
        page = self._doc.pages[index]
        text = page.extract_text()
        return text if text else ""
