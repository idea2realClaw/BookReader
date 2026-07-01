from .base import BookReader, BookMetadata
from .txt_reader import TxtReader
from .epub_reader import EpubReader
from .pdf_reader import PdfReader


def open_book(path: str) -> BookReader:
    lower = path.lower()
    if lower.endswith(".txt"):
        return TxtReader(path)
    if lower.endswith(".epub"):
        return EpubReader(path)
    if lower.endswith(".pdf"):
        return PdfReader(path)
    raise ValueError(f"不支持的格式: {path}")
