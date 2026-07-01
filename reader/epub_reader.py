import os
import re
import zipfile
from html.parser import HTMLParser
from typing import List
from .base import BookReader, BookMetadata


class _TextExtractor(HTMLParser):
    """Collect visible text from HTML, dropping script/style tags."""

    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav"):
            self._skip += 1
        elif tag == "br":
            self._text.append("\n")
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._text.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav"):
            self._skip -= 1
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._text.append("\n")

    def handle_data(self, data):
        if self._skip == 0:
            self._text.append(data)

    def get_text(self) -> str:
        raw = "".join(self._text)
        # Collapse multiple whitespace/newlines.
        return re.sub(r"[ \t]*\n[ \t]*\n+", "\n\n", raw).strip()


class EpubReader(BookReader):
    """EPUB reader using only standard library (zipfile + html.parser)."""

    PAGE_SIZE = 700

    def __init__(self, path: str):
        super().__init__(path)
        self.pages: List[str] = []

    def load(self) -> None:
        title = os.path.splitext(os.path.basename(self.path))[0]
        author = "未知作者"

        with zipfile.ZipFile(self.path, "r") as zf:
            # Read container to find OPF path.
            container = zf.read("META-INF/container.xml").decode("utf-8", errors="ignore")
            opf_match = re.search(r'<rootfile[^>]+full-path="([^"]+)"', container)
            opf_path = opf_match.group(1) if opf_match else "OEBPS/content.opf"
            opf_dir = os.path.dirname(opf_path)

            opf = zf.read(opf_path).decode("utf-8", errors="ignore")

            # Extract metadata.
            title_match = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', opf, re.I)
            if title_match:
                title = title_match.group(1).strip()
            author_match = re.search(r'<dc:creator[^>]*>([^<]+)</dc:creator>', opf, re.I)
            if author_match:
                author = author_match.group(1).strip()

            self.metadata = BookMetadata(title=title, author=author)

            # Parse spine item order.
            spine_match = re.search(r'<spine[^>]*>(.*?)</spine>', opf, re.S | re.I)
            idref_list = []
            if spine_match:
                idref_list = re.findall(r'<itemref[^>]+idref="([^"]+)"', spine_match.group(1))

            # Build id -> href mapping (order-independent attribute matching).
            item_map = {}
            for item_match in re.finditer(r'<item\b([^>]+)>', opf, re.I):
                attrs = item_match.group(1)
                id_m = re.search(r'\bid="([^"]+)"', attrs, re.I)
                href_m = re.search(r'\bhref="([^"]+)"', attrs, re.I)
                media_m = re.search(r'\bmedia-type="([^"]+)"', attrs, re.I)
                if id_m and href_m and media_m:
                    media = media_m.group(1)
                    if "xhtml" in media or "html" in media:
                        item_map[id_m.group(1)] = os.path.join(opf_dir, href_m.group(1)).replace("\\", "/")

            # Read documents in spine order.
            full_text = ""
            for idref in idref_list:
                href = item_map.get(idref)
                if not href:
                    continue
                try:
                    html = zf.read(href).decode("utf-8", errors="ignore")
                except KeyError:
                    continue
                extractor = _TextExtractor()
                extractor.feed(html)
                text = extractor.get_text()
                if text:
                    full_text += text + "\n\n"

        self.pages = self._split(full_text)

    def _split(self, text: str) -> List[str]:
        pages = []
        for i in range(0, len(text), self.PAGE_SIZE):
            pages.append(text[i : i + self.PAGE_SIZE])
        return pages or [""]

    def get_page_count(self) -> int:
        return len(self.pages)

    def get_page(self, index: int) -> str:
        return self.pages[index]
