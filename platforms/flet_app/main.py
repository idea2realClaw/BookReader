"""
Flet App - 使用共享核心逻辑

这个模块是 Flet UI 层，调用 core 模块的业务逻辑
"""

import sys
import os

# 添加 core 模块到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../core'))

import flet as ft
from core.src import BookRepository, create_parser, Book


class BookReaderApp:
    """Flet 应用主类"""
    
    def __init__(self):
        self.repo = BookRepository()
        self.current_book: Optional[Book] = None
        self.parser = None
    
    def main(self, page: ft.Page):
        """Flet 应用入口"""
        self.page = page
        page.title = "BookReader"
        page.window_width = 1400
        page.window_height = 900
        
        # 显示书架
        self.show_bookshelf()
    
    def show_bookshelf(self):
        """显示书架界面"""
        self.page.controls.clear()
        
        # 标题
        title = ft.Text("我的书架", size=32, weight=ft.FontWeight.BOLD)
        
        # 添加书籍按钮
        add_btn = ft.ElevatedButton(
            "添加书籍",
            icon=ft.icons.ADD,
            on_click=self.pick_file
        )
        
        # 书籍列表
        book_list = ft.ListView(
            controls=[
                self._create_book_card(book) for book in self.repo.books
            ],
            spacing=10,
            padding=20
        )
        
        self.page.add(
            ft.Column([
                title,
                add_btn,
                ft.Divider(),
                book_list if self.repo.books else ft.Text("暂无书籍，点击上方按钮添加", size=16)
            ])
        )
        self.page.update()
    
    def _create_book_card(self, book: Book) -> ft.Card:
        """创建书籍卡片"""
        return ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text(book.title, size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(f"格式: {book.format.upper()} | 页数: {book.total_pages}", size=14),
                    ft.Text(f"当前进度: 第 {book.current_page + 1} 页", size=12, color=ft.colors.GREY_600),
                    ft.ElevatedButton(
                        "继续阅读",
                        on_click=lambda e, b=book: self.open_book(b)
                    )
                ]),
                padding=20
            )
        )
    
    def pick_file(self, e):
        """选择文件"""
        file_picker = ft.FilePicker(
            on_result=self._on_file_picked
        )
        self.page.overlay.append(file_picker)
        self.page.update()
        
        file_picker.pick_files(
            allowed_extensions=['txt', 'epub', 'pdf'],
            allow_multiple=False
        )
    
    def _on_file_picked(self, e: ft.FilePickerResultEvent):
        """文件选择回调"""
        if e.files:
            file_path = e.files[0].path
            self._load_book(file_path)
    
    def _load_book(self, file_path: str):
        """加载书籍"""
        try:
            self.parser = create_parser(file_path)
            book = self.parser.parse(file_path)
            
            # 添加到仓库
            existing = self.repo.get_book(book.id)
            if existing:
                book.current_page = existing.current_page
                book.bookmarks = existing.bookmarks
            
            self.repo.add_book(book)
            self.current_book = book
            
            self.show_bookshelf()
        except Exception as e:
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text(f"加载失败: {e}")))
    
    def open_book(self, book: Book):
        """打开书籍阅读"""
        self.current_book = book
        self.parser = create_parser(book.path)
        self.parser.parse(book.path)
        
        self.show_reader()
    
    def show_reader(self):
        """显示阅读界面"""
        if not self.current_book or not self.parser:
            return
        
        self.page.controls.clear()
        
        # 获取当前页内容
        page_data = self.parser.get_page(self.current_book.current_page)
        
        # 顶部工具栏
        appbar = ft.AppBar(
            leading=ft.IconButton(
                ft.icons.ARROW_BACK,
                on_click=lambda e: self.show_bookshelf()
            ),
            title=ft.Text(self.current_book.title),
            actions=[
                ft.IconButton(ft.icons.BOOKMARK, on_click=self.add_bookmark)
            ]
        )
        
        # 内容显示
        content = ft.Text(
            page_data.content,
            size=16,
            selectable=True
        )
        
        # 底部导航
        nav_bar = ft.Row([
            ft.ElevatedButton(
                "上一页",
                on_click=self.prev_page,
                disabled=self.current_book.current_page <= 0
            ),
            ft.Text(f"第 {self.current_book.current_page + 1} / {self.current_book.total_pages} 页"),
            ft.ElevatedButton(
                "下一页",
                on_click=self.next_page,
                disabled=self.current_book.current_page >= self.current_book.total_pages - 1
            )
        ], alignment=ft.MainAxisAlignment.CENTER)
        
        self.page.add(appbar, ft.Divider(), content, nav_bar)
        self.page.update()
    
    def prev_page(self, e):
        """上一页"""
        if self.current_book and self.current_book.current_page > 0:
            self.current_book.current_page -= 1
            self.repo.update_progress(self.current_book.id, self.current_book.current_page)
            self.show_reader()
    
    def next_page(self, e):
        """下一页"""
        if self.current_book and self.current_book.current_page < self.current_book.total_pages - 1:
            self.current_book.current_page += 1
            self.repo.update_progress(self.current_book.id, self.current_book.current_page)
            self.show_reader()
    
    def add_bookmark(self, e):
        """添加书签"""
        if self.current_book:
            self.repo.add_bookmark(self.current_book.id, self.current_book.current_page)
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("已添加书签")))


if __name__ == "__main__":
    app = BookReaderApp()
    ft.app(target=app.main, assets_dir="assets")
