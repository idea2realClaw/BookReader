import os
import tempfile
import asyncio
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
        """打开文件选择器，支持桌面和浏览器模式"""
        print(f"\n[BookShelf] ===== FilePicker started =====")
        print(f"[BookShelf] Is web mode: {self.ft_page.web}")
        print(f"[BookShelf] Event trigger: {type(e)}")
        
        try:
            # 步骤1: 最简单的调用，不带任何过滤
            print(f"[BookShelf] Step 1: Calling FilePicker without filters...")
            result = await ft.FilePicker().pick_files(allow_multiple=False)
            print(f"[BookShelf] Step 1 result: {result}")
            
            if not result or len(result) == 0:
                print(f"[BookShelf] No file selected, aborting")
                return
            
            file = result[0]
            print(f"[BookShelf] Selected file: name={file.name}, path={file.path}, has_bytes={file.bytes is not None}")
            
            # 步骤2: 根据模式处理文件
            if file.path:  # 桌面模式
                print(f"[BookShelf] Desktop mode: using path directly")
                self._add_book(file.path)
                self._refresh_grid()
                return
            
            # 浏览器模式：需要获取文件内容
            print(f"[BookShelf] Browser mode: need to get file content")
            
            # 步骤3: 使用 with_data=True 重新选择文件
            print(f"[BookShelf] Step 2: Calling FilePicker with with_data=True...")
            result2 = await ft.FilePicker().pick_files(
                allow_multiple=False,
                with_data=True
            )
            
            if not result2 or len(result2) == 0:
                print(f"[BookShelf] No file selected in step 2")
                return
            
            file2 = result2[0]
            print(f"[BookShelf] Step 2 result: name={file2.name}, has_bytes={file2.bytes is not None}")
            
            if file2.bytes:
                # 保存到临时文件
                temp_dir = os.path.join(os.path.dirname(__file__), "..", "temp")
                os.makedirs(temp_dir, exist_ok=True)
                temp_path = os.path.join(temp_dir, file2.name)
                
                print(f"[BookShelf] Saving to temp file: {temp_path}")
                with open(temp_path, "wb") as fp:
                    fp.write(file2.bytes)
                
                self._temp_files.append(temp_path)
                self._add_book(temp_path)
                self._refresh_grid()
            else:
                print(f"[BookShelf] ERROR: Still no file data after with_data=True")
                self.ft_page.snack_bar = ft.SnackBar(
                    content=ft.Text(f"无法读取文件内容，请重试"),
                    action="OK"
                )
                self.ft_page.snack_bar.open = True
                self.ft_page.update()
            
        except Exception as ex:
            print(f"[BookShelf] ERROR: {ex}")
            print(f"[BookShelf] Error type: {type(ex)}")
            import traceback
            traceback.print_exc()
            
            # 显示错误给用户
            self.ft_page.snack_bar = ft.SnackBar(
                content=ft.Text(f"文件选择失败: {ex}"),
                action="OK"
            )
            self.ft_page.snack_bar.open = True
            self.ft_page.update()
        
        finally:
            print(f"[BookShelf] ===== FilePicker finished =====\n")

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
                    on_click=lambda e, p=book["path"]: asyncio.create_task(self._open_book(p)),
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
