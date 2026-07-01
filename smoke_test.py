"""Smoke tests for BookReader parsers and UI construction."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader import open_book
from ui.book_viewer import BookViewer
from ui.bookshelf import BookShelf
import flet as ft


ASSETS = os.path.join(os.path.dirname(__file__), "assets")


def test_txt():
    path = os.path.join(ASSETS, "sample.txt")
    reader = open_book(path)
    reader.load()
    assert reader.get_page_count() > 0
    assert "风起" in reader.get_page(0)
    print("[OK] TXT")


def test_pdf():
    path = os.path.join(ASSETS, "sample.pdf")
    reader = open_book(path)
    reader.load()
    assert reader.get_page_count() == 2
    assert "Sample PDF" in reader.get_page(0)
    print("[OK] PDF")


def test_epub():
    path = os.path.join(ASSETS, "sample.epub")
    reader = open_book(path)
    reader.load()
    assert reader.get_page_count() > 0
    assert "启程" in reader.get_page(0)
    print("[OK] EPUB")


test_txt()
test_pdf()
test_epub()
print("所有解析器测试通过。")


async def main(page: ft.Page):
    page.title = "Smoke Test"
    page.padding = 0

    shelf = BookShelf(page)
    page.views.append(shelf)
    page.update()

    path = os.path.join(ASSETS, "sample.txt")
    reader = open_book(path)
    reader.load()
    viewer = BookViewer(reader, page, on_close=lambda: os._exit(0))
    page.views.append(ft.View(route="/read", controls=[viewer]))
    await page.push_route("/read")
    print("UI 构造成功。")

    def close_later():
        time.sleep(3)
        os._exit(0)

    threading.Thread(target=close_later, daemon=True).start()


ft.run(main, assets_dir="assets")
