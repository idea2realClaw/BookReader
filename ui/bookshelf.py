import os
import asyncio
import json
import datetime
import flet as ft
from reader import open_book
from ui.book_viewer import BookViewer

# 书籍数据持久化文件路径
BOOKS_JSON_PATH = os.path.expanduser("~/.bookreader/books.json")


class BookShelf(ft.Container):
    """Library view: pick a file and open the reader."""

    def __init__(self, main_window):
        super().__init__(expand=True)
        self.main_window = main_window
        self.ft_page = main_window.ft_page
        self.books = []  # List of dicts: {path, title, author, pages}
        self._temp_files = []  # Track temp files for cleanup
        
        # 从本地存储加载已保存的书籍
        self._load_books()
        
        self._build()
        
        # 刷新网格以显示加载的书籍
        self._refresh_grid()

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

        # 使用 Column 作为主布局
        self.content = ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("我的书架", size=20, weight=ft.FontWeight.BOLD),
                            ft.Row(
                                [
                                    ft.IconButton(
                                        ft.Icons.FOLDER_OPEN,
                                        tooltip="添加书籍",
                                        on_click=self._pick_file,
                                    ),
                                    ft.IconButton(
                                        ft.Icons.EDIT,
                                        tooltip="手动输入路径",
                                        on_click=self._show_path_input,
                                    ),
                                    ft.IconButton(
                                        ft.Icons.REFRESH,
                                        tooltip="清除缓存并刷新 (或按 Ctrl+F5)",
                                        on_click=self._clear_cache,
                                    ),
                                ],
                                spacing=0,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=10,
                    bgcolor=ft.Colors.BLUE,
                    border_radius=10,
                ),
                ft.Container(
                    content=self.grid,
                    expand=True,
                    padding=10,
                ),
            ],
            spacing=0,
            expand=True,
        )

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
        """显示手动输入路径的浮层"""
        print(f"\n[BookShelf] ===== 打开路径输入浮层 =====")
        
        try:
            path_input = ft.TextField(
                label="输入文件路径",
                hint_text="例如: assets/sample.txt",
                width=400,
            )
            
            def add_from_path(e):
                print(f"[BookShelf] 点击'添加'按钮")
                path = path_input.value.strip()
                if not path:
                    return
                
                print(f"[BookShelf] 手动添加路径: {path}")
                
                if not os.path.exists(path):
                    print(f"[BookShelf] 文件不存在: {path}")
                    self.ft_page.snack_bar = ft.SnackBar(
                        content=ft.Text(f"文件不存在: {path}"),
                        action="OK"
                    )
                    self.ft_page.snack_bar.open = True
                else:
                    print(f"[BookShelf] 文件存在，添加书籍...")
                    self._add_book(path)
                    self._refresh_grid()
                
                # 隐藏浮层
                print(f"[BookShelf] 隐藏输入浮层...")
                self._hide_path_input()
            
            def cancel_input(e):
                print(f"[BookShelf] 点击'取消'按钮")
                self._hide_path_input()
            
            # 创建浮层容器
            self._path_input_overlay = ft.Container(
                content=ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("手动输入文件路径", size=18, weight=ft.FontWeight.BOLD),
                                ft.Container(height=10),
                                path_input,
                                ft.Text(
                                    "提示: 可以输入相对路径（如 assets/sample.txt）或绝对路径",
                                    size=11,
                                    color=ft.Colors.BLACK54,
                                ),
                                ft.Container(height=10),
                                ft.Row(
                                    [
                                        ft.TextButton("取消", on_click=cancel_input),
                                        ft.TextButton("添加", on_click=add_from_path),
                                    ],
                                    alignment=ft.MainAxisAlignment.END,
                                ),
                            ],
                            tight=True,
                        ),
                        padding=20,
                        bgcolor=ft.Colors.WHITE,  # 显式设置背景色
                        border_radius=10,
                    ),
                    elevation=20,  # 高阴影，确保可见
                ),
                # 绝对定位：居中显示
                left=0,
                right=0,
                top=0,
                bottom=0,
                alignment=ft.Alignment.CENTER,
                bgcolor=ft.Colors.BLACK12,  # 半透明背景
            )
            
            print(f"[BookShelf] 创建浮层完成，显示浮层...")
            
            # 添加到页面
            self.ft_page.overlay.append(self._path_input_overlay)
            self._path_input_overlay.visible = True
            self.ft_page.update()
            
            print(f"[BookShelf] 浮层已显示")
            print(f"[BookShelf] ===== 路径输入浮层已打开 =====\n")
            
        except Exception as ex:
            print(f"[BookShelf] 错误: {ex}")
            import traceback
            traceback.print_exc()
        
    def _hide_path_input(self):
        """隐藏路径输入浮层"""
        if hasattr(self, '_path_input_overlay') and self._path_input_overlay:
            print(f"[BookShelf] 隐藏浮层...")
            self._path_input_overlay.visible = False
            # 从 overlay 中移除
            if self._path_input_overlay in self.ft_page.overlay:
                self.ft_page.overlay.remove(self._path_input_overlay)
            self.ft_page.update()
            print(f"[BookShelf] 浮层已隐藏")
    
    def _clear_cache(self, e):
        """显示清除缓存的说明"""
        print("\n" + "="*50)
        print("[BookShelf] 清除缓存说明")
        print("="*50)
        print("浏览器缓存可能导致应用无法加载最新版本。")
        print("")
        print("方法 1：强制刷新（推荐）")
        print("  Windows/Linux: 按 Ctrl + F5")
        print("  Mac: 按 Cmd + Shift + R")
        print("")
        print("方法 2：使用浏览器开发者工具")
        print("  1. 按 F12 打开开发者工具")
        print("  2. 右键点击刷新按钮")
        print("  3. 选择'清空缓存并硬性重新加载'")
        print("")
        print("方法 3：手动清除缓存")
        print("  Chrome/Edge: 按 Ctrl + Shift + Delete")
        print("  Firefox: 按 Ctrl + Shift + Delete")
        print("  然后选择'缓存的图片和文件'并清除")
        print("="*50 + "\n")
        
        # 在 UI 中显示说明
        self.ft_page.snack_bar = ft.SnackBar(
            content=ft.Text("已输出缓存清理说明到日志窗口，请查看下方日志"),
            action="OK",
            duration=3,
        )
        self.ft_page.snack_bar.open = True
        self.ft_page.update()

    def _save_books(self):
        """将书籍列表保存到 JSON 文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(BOOKS_JSON_PATH), exist_ok=True)
            
            # 保存到 JSON 文件
            with open(BOOKS_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.books, f, ensure_ascii=False, indent=2)
            
            print(f"[BookShelf] 书籍已保存到: {BOOKS_JSON_PATH}")
        except Exception as e:
            print(f"[BookShelf] 保存书籍失败: {e}")

    def _load_books(self):
        """从 JSON 文件加载书籍列表"""
        try:
            if not os.path.exists(BOOKS_JSON_PATH):
                print(f"[BookShelf] 未找到书籍文件，将从空书架开始")
                return
            
            with open(BOOKS_JSON_PATH, 'r', encoding='utf-8') as f:
                saved_books = json.load(f)
            
            # 验证文件是否仍然存在
            valid_books = []
            for book in saved_books:
                if os.path.exists(book["path"]):
                    valid_books.append(book)
                else:
                    print(f"[BookShelf] 书籍文件不再存在: {book['path']}")
            
            self.books = valid_books
            print(f"[BookShelf] 从 {BOOKS_JSON_PATH} 加载了 {len(self.books)} 本书")
            
        except Exception as e:
            print(f"[BookShelf] 加载书籍失败: {e}")
            self.books = []

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
            
            # 保存书籍列表到本地文件
            self._save_books()
        except Exception as ex:
            print(f"[BookShelf] ERROR adding book: {path}, {ex}")
            import traceback
            traceback.print_exc()

    def _refresh_grid(self):
        self.grid.controls.clear()
        for book in self.books:
            # 使用简单的 TextButton 作为书籍卡片
            book_btn = ft.TextButton(
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
                                color=ft.Colors.BLACK87,
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
                    expand=True,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=10,
                ),
                on_click=lambda e, p=book["path"]: self._on_book_clicked(p),
            )
            
            # 直接把按钮放入卡片（不使用 Stack）
            card = ft.Card(
                content=book_btn,
                elevation=4,
            )
            self.grid.controls.append(card)
        self.ft_page.update()
        print(f"[BookShelf] 刷新网格完成，共 {len(self.books)} 本书")
    
    def _on_book_clicked(self, path: str):
        """处理书籍点击事件"""
        # 直接写入文件（不依赖 print）
        with open("click_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"点击时间: {datetime.datetime.now()}\n")
            f.write(f"书籍路径: {path}\n")
            f.write(f"{'='*50}\n")
        
        print(f"\n[BookShelf] 🖱️ 书籍被点击！")
        print(f"[BookShelf]   路径: {path}")
        asyncio.create_task(self._open_book(path))
    
    def _make_remove_handler(self, path: str):
        """工厂函数：创建删除按钮点击处理器（带日志）"""
        def handler(e):
            print(f"\n[BookShelf] 🗑️ 删除按钮被点击！")
            print(f"[BookShelf]   路径: {path}")
            self._remove_book(path)
        return handler

    async def _open_book(self, path: str):
        print(f"\n[BookShelf] ===== 开始打开书籍 =====")
        print(f"[BookShelf] Opening book: {path}")
        try:
            print(f"[BookShelf] 创建 reader...")
            reader = open_book(path)
            print(f"[BookShelf] Reader created: {type(reader).__name__}")
            
            print(f"[BookShelf] 加载书籍内容...")
            reader.load()
            print(f"[BookShelf] Reader loaded successfully")
            print(f"[BookShelf] Title: {reader.metadata.title}")
            print(f"[BookShelf] Author: {reader.metadata.author}")
            print(f"[BookShelf] Pages: {reader.get_page_count()}")
            
            print(f"[BookShelf] 创建 BookViewer...")
            viewer = BookViewer(reader, self.main_window, on_close=self._back_to_shelf)
            print(f"[BookShelf] BookViewer created")
            
            print(f"[BookShelf] 导航到阅读器...")
            self.main_window.navigate_to_viewer(viewer)
            print(f"[BookShelf] ===== 书籍打开成功 =====\n")
            
        except Exception as e:
            print(f"\n[BookShelf] ERROR opening book: {e}")
            import traceback
            traceback.print_exc()
            # Show error to user
            self.ft_page.snack_bar = ft.SnackBar(
                content=ft.Text(f"打开书籍失败: {e}"),
                action="OK"
            )
            self.ft_page.snack_bar.open = True
            self.ft_page.update()
            print(f"[BookShelf] ===== 书籍打开失败 =====\n")

    def _remove_book(self, path: str):
        """从书架移除书籍"""
        self.books = [b for b in self.books if b["path"] != path]
        self._save_books()
        self._refresh_grid()
        print(f"[BookShelf] 🗑️ 已移除书籍: {path}")

    async def _back_to_shelf(self):
        print(f"\n[BookShelf] 🔙 返回书架...")
        self.main_window.navigate_to_shelf()
        print(f"[BookShelf] ✅ 已返回书架\n")
        print(f"[BookShelf] 已返回书架\n")
