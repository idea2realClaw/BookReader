import os
import flet as ft
from reader import open_book
from ui.book_viewer import BookViewer


class BookShelf(ft.View):
    """Library view: pick a file and open the reader."""

    def __init__(self, page: ft.Page):
        super().__init__(route="/")
        self.ft_page = page
        self.books = []
        self._build()

    def _build(self):
        self.grid = ft.GridView(
            expand=True,
            runs_count=3,
            max_extent=150,
            child_aspect_ratio=0.7,
            spacing=10,
            run_spacing=10,
            padding=10,
        )

        self.controls = [
            ft.AppBar(
                title=ft.Text("我的书架"),
                center_title=True,
                bgcolor=ft.Colors.BLUE,
                color=ft.Colors.WHITE,
                actions=[
                    ft.IconButton(
                        ft.Icons.FOLDER_OPEN,
                        tooltip="添加书籍",
                        icon_color=ft.Colors.WHITE,
                        on_click=self._pick_file,
                    )
                ],
            ),
            ft.Container(
                content=self.grid,
                expand=True,
                padding=10,
            ),
        ]

    async def _pick_file(self, e):
        files = await ft.FilePicker().pick_files(
            allow_multiple=True,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["txt", "epub", "pdf"],
        )
        self._process_picked_files(files or [])

    def _process_picked_files(self, files):
        for f in files:
            path = f.path
            if not path:
                continue
            lower = path.lower()
            if lower.endswith((".txt", ".epub", ".pdf")):
                self._add_book(path)
        self._refresh_grid()


    def _add_book(self, path: str):
        if any(b["path"] == path for b in self.books):
            return
        try:
            reader = open_book(path)
            reader.load()
            self.books.append({
                "path": path,
                "title": reader.metadata.title,
                "author": reader.metadata.author,
                "pages": reader.get_page_count(),
            })
        except Exception as ex:
            print(f"添加书籍失败: {path}, {ex}")

    def _refresh_grid(self):
        self.grid.controls.clear()
        for book in self.books:
            card = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.BOOK, size=48, color=ft.Colors.BLUE),
                            ft.Text(
                                book["title"],
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                book["author"],
                                size=11,
                                color=ft.Colors.BLACK54,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{book['pages']} 页",
                                size=10,
                                color=ft.Colors.BLACK38,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=10,
                    alignment=ft.Alignment.CENTER,
                    on_click=lambda e, p=book["path"]: self._open_book(p),
                ),
                elevation=4,
            )
            self.grid.controls.append(card)
        self.ft_page.update()

    async def _open_book(self, path: str):
        reader = open_book(path)
        reader.load()
        viewer = BookViewer(reader, self.ft_page, on_close=self._back_to_shelf)
        self.ft_page.views.clear()
        self.ft_page.views.append(self)
        self.ft_page.views.append(ft.View(route="/read", controls=[viewer]))
        await self.ft_page.push_route("/read")

    async def _back_to_shelf(self):
        self.ft_page.views.pop()
        await self.ft_page.push_route("/")
