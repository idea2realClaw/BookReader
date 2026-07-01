import os
import tempfile
import flet as ft
from reader import open_book
from ui.book_viewer import BookViewer


class BookShelf(ft.View):
    """Library view: pick a file and open the reader."""

    def __init__(self, page: ft.Page):
        super().__init__(route="/")
        self.ft_page = page
        self.books = []  # List of dicts: {path, title, author, pages}
        self._temp_files = []  # Track temp files for cleanup
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
        print(f"[BookShelf] FilePicker opened")
        try:
            files = await ft.FilePicker().pick_files(
                allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["txt", "epub", "pdf"],
                with_data=True,  # Important: Get file content in browser mode
            )
            print(f"[BookShelf] FilePicker result: {files}")
            
            if not files:
                print("[BookShelf] No files selected")
                return
            
            # Process files - handle both desktop (path) and web/browser mode (bytes)
            for f in files:
                print(f"[BookShelf] Processing: {f.name} (path={f.path}, has_bytes={f.bytes is not None})")
                
                if f.path:  # Desktop mode - direct file path
                    print(f"[BookShelf] Desktop mode: using path {f.path}")
                    self._add_book(f.path)
                elif f.bytes:  # Browser mode - save to temp file
                    print(f"[BookShelf] Browser mode: saving {f.name} to temp file")
                    temp_dir = os.path.join(os.path.dirname(__file__), "..", "temp")
                    os.makedirs(temp_dir, exist_ok=True)
                    temp_path = os.path.join(temp_dir, f.name)
                    
                    with open(temp_path, "wb") as fp:
                        fp.write(f.bytes)
                    
                    print(f"[BookShelf] Saved to: {temp_path}")
                    self._temp_files.append(temp_path)
                    self._add_book(temp_path)
                else:
                    print(f"[BookShelf] ERROR: File {f.name} has no path and no bytes")
            
            print("[BookShelf] Refreshing grid...")
            self._refresh_grid()
            print("[BookShelf] Grid refreshed")
            
        except Exception as ex:
            print(f"[BookShelf] FilePicker ERROR: {ex}")
            import traceback
            traceback.print_exc()

    def _process_picked_files(self, files):
        print(f"[BookShelf] _process_picked_files called with {len(files) if files else 0} files")
        if not files:
            print("[BookShelf] No files to process")
            return
        
        for f in files:
            print(f"[BookShelf] Processing file: {f}")
            path = f.path if hasattr(f, 'path') else str(f)
            print(f"[BookShelf] File path: {path}")
            if not path:
                print("[BookShelf] Empty path, skipping")
                continue
            lower = path.lower()
            if lower.endswith((".txt", ".epub", ".pdf")):
                print(f"[BookShelf] Valid file type, adding to shelf: {path}")
                self._add_book(path)
            else:
                print(f"[BookShelf] Invalid file type: {path}")
        print("[BookShelf] Refreshing grid...")
        self._refresh_grid()
        print("[BookShelf] Grid refreshed")


    def _add_book(self, path: str):
        if any(b["path"] == path for b in self.books):
            print(f"[BookShelf] Book already in shelf: {path}")
            return
        try:
            print(f"[BookShelf] Adding book: {path}")
            reader = open_book(path)
            reader.load()
            self.books.append({
                "path": path,
                "title": reader.metadata.title,
                "author": reader.metadata.author,
                "pages": reader.get_page_count(),
            })
            print(f"[BookShelf] Book added successfully: {reader.metadata.title}")
        except Exception as ex:
            print(f"[BookShelf] ERROR adding book: {path}, {ex}")
            import traceback
            traceback.print_exc()

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
                    on_click=lambda e, p=book["path"]: self.ft_page.run(self._open_book, p),
                ),
                elevation=4,
            )
            self.grid.controls.append(card)
        self.ft_page.update()

    async def _open_book(self, path: str):
        print(f"[BookShelf] Opening book: {path}")
        try:
            reader = open_book(path)
            print(f"[BookShelf] Reader created: {type(reader).__name__}")
            
            reader.load()
            print(f"[BookShelf] Reader loaded successfully")
            print(f"[BookShelf] Title: {reader.metadata.title}")
            print(f"[BookShelf] Pages: {reader.get_page_count()}")
            
            viewer = BookViewer(reader, self.ft_page, on_close=self._back_to_shelf)
            print(f"[BookShelf] BookViewer created")
            
            self.ft_page.views.clear()
            self.ft_page.views.append(self)
            self.ft_page.views.append(ft.View(route="/read", controls=[viewer]))
            print(f"[BookShelf] Views updated, pushing route...")
            
            await self.ft_page.push_route("/read")
            print(f"[BookShelf] Route pushed successfully")
            
        except Exception as e:
            print(f"[BookShelf] ERROR opening book: {e}")
            import traceback
            traceback.print_exc()
            # Show error to user
            self.ft_page.snack_bar = ft.SnackBar(
                content=ft.Text(f"打开书籍失败: {e}"),
                action="OK"
            )
            self.ft_page.snack_bar.open = True
            self.ft_page.update()

    async def _back_to_shelf(self):
        self.ft_page.views.pop()
        await self.ft_page.push_route("/")
