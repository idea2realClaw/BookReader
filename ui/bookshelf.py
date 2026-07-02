import os
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
                    ),
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="手动输入路径",
                        icon_color=ft.Colors.WHITE,
                        on_click=self._show_path_input,
                    ),
                ],
            ),
            ft.Container(
                content=self.grid,
                expand=True,
                padding=10,
            ),
        ]

    async def _pick_file(self, e):
        """打开文件选择器"""
        print(f"\n[BookShelf] 开始选择文件...")
        print(f"[BookShelf] 模式: {'浏览器' if self.ft_page.web else '桌面'}")
        
        try:
            # 最简单的调用
            files = await ft.FilePicker().pick_files(allow_multiple=False)
            
            if not files:
                print(f"[BookShelf] 用户取消选择")
                return
            
            file = files[0]
            print(f"[BookShelf] 选中文件: {file.name}")
            print(f"[BookShelf]   path={file.path}")
            print(f"[BookShelf]   bytes={'有' if file.bytes else '无'}")
            
            # 桌面模式：直接使用路径
            if file.path:
                print(f"[BookShelf] 桌面模式，直接添加")
                self._add_book(file.path)
                self._refresh_grid()
                return
            
            # 浏览器模式：提示用户
            print(f"[BookShelf] 浏览器模式下 FilePicker 暂不支持")
            print(f"[BookShelf] 请使用桌面模式，或手动将文件放到 temp 目录")
            
            self.ft_page.snack_bar = ft.SnackBar(
                content=ft.Text(f"浏览器模式暂不支持文件选择，请使用桌面模式"),
                action="OK"
            )
            self.ft_page.snack_bar.open = True
            self.ft_page.update()
            
        except Exception as ex:
            print(f"[BookShelf] 错误: {ex}")
            import traceback
            traceback.print_exc()
            
            self.ft_page.snack_bar = ft.SnackBar(
                content=ft.Text(f"错误: {ex}"),
                action="OK"
            )
            self.ft_page.snack_bar.open = True
            self.ft_page.update()
        
        finally:
            print(f"[BookShelf] 选择文件结束\n")

    async def _show_path_input(self, e):
        """显示手动输入路径的对话框"""
        print(f"[BookShelf] 打开路径输入对话框...")
        
        path_input = ft.TextField(
            label="输入文件路径",
            hint_text="例如: assets/sample.txt",
            width=300,
        )
        
        def add_from_path(e):
            path = path_input.value.strip()
            if not path:
                return
            
            print(f"[BookShelf] 手动添加路径: {path}")
            
            # 检查文件是否存在
            if not os.path.exists(path):
                print(f"[BookShelf] 文件不存在: {path}")
                self.ft_page.snack_bar = ft.SnackBar(
                    content=ft.Text(f"文件不存在: {path}"),
                    action="OK"
                )
                self.ft_page.snack_bar.open = True
            else:
                # 添加书籍
                self._add_book(path)
                self._refresh_grid()
            
            # 关闭对话框
            dialog.open = False
            self.ft_page.update()
        
        dialog = ft.AlertDialog(
            modal=True,  # 设置为模态对话框
            title=ft.Text("手动输入文件路径"),
            content=ft.Column(
                [
                    path_input,
                    ft.Text(
                        "提示: 可以输入相对路径（如 assets/sample.txt）或绝对路径",
                        size=11,
                        color=ft.Colors.BLACK54,
                    ),
                ],
                tight=True,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog(dialog)),
                ft.TextButton("添加", on_click=add_from_path),
            ],
        )
        
        print(f"[BookShelf] 显示对话框...")
        self.ft_page.dialog = dialog
        dialog.open = True
        self.ft_page.update()
        print(f"[BookShelf] 对话框已显示")
    
    def _close_dialog(self, dialog):
        """关闭对话框"""
        dialog.open = False
        self.ft_page.update()

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
            
            # 创建阅读视图，设置 expand=True 让它铺满
            read_view = ft.View(
                route="/read",
                controls=[viewer],
                appbar=None,  # 不使用默认 appbar
                padding=0,  # 无边距
            )
            
            self.ft_page.views.clear()
            self.ft_page.views.append(self)
            self.ft_page.views.append(read_view)
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
