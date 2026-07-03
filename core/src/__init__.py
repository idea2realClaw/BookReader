"""
BookReader Core - 跨平台核心逻辑层

这个模块包含所有平台共享的业务逻辑：
- 书籍解析（TXT/EPUB/PDF）
- 分页算法
- 阅读进度管理
- 书签管理

设计原则：
1. 纯逻辑，无 UI 依赖
2. 可被 Flet、Android、iOS、Web 等任意平台调用
3. 使用 Python 编写（Android 通过 Chaquopy 调用）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict
import json
from pathlib import Path


@dataclass
class Book:
    """书籍数据模型"""
    id: str
    title: str
    author: str
    path: str
    format: str  # 'txt', 'epub', 'pdf'
    total_pages: int
    current_page: int = 0
    bookmarks: List[int] = None
    
    def __post_init__(self):
        if self.bookmarks is None:
            self.bookmarks = []


@dataclass
class Page:
    """页面数据模型"""
    page_num: int
    content: str
    chapter_title: Optional[str] = None


class BookParser(ABC):
    """书籍解析器抽象基类"""
    
    @abstractmethod
    def parse(self, file_path: str) -> Book:
        """解析书籍文件，返回 Book 对象"""
        pass
    
    @abstractmethod
    def get_page(self, page_num: int) -> Page:
        """获取指定页的内容"""
        pass
    
    @abstractmethod
    def get_total_pages(self) -> int:
        """获取总页数"""
        pass


class TXTParser(BookParser):
    """TXT 文件解析器"""
    
    def __init__(self, file_path: str, chars_per_page: int = 2000):
        self.file_path = file_path
        self.chars_per_page = chars_per_page
        self._content = ""
        self._pages = []
    
    def parse(self, file_path: str = None) -> Book:
        """解析 TXT 文件"""
        path = file_path or self.file_path
        
        # 读取文件内容
        with open(path, 'r', encoding='utf-8') as f:
            self._content = f.read()
        
        # 计算分页
        self._pages = [
            self._content[i:i + self.chars_per_page]
            for i in range(0, len(self._content), self.chars_per_page)
        ]
        
        # 提取标题（前两行非空文本）
        lines = [line.strip() for line in self._content.split('\n') if line.strip()]
        title = lines[0] if lines else Path(path).stem
        
        return Book(
            id=Path(path).stem,
            title=title,
            author="",
            path=path,
            format='txt',
            total_pages=len(self._pages)
        )
    
    def get_page(self, page_num: int) -> Page:
        """获取指定页内容"""
        if 0 <= page_num < len(self._pages):
            return Page(
                page_num=page_num,
                content=self._pages[page_num]
            )
        raise IndexError(f"Page {page_num} out of range")
    
    def get_total_pages(self) -> int:
        """获取总页数"""
        return len(self._pages)


class EPUBParser(BookParser):
    """EPUB 文件解析器"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._chapters = []
    
    def parse(self, file_path: str = None) -> Book:
        """解析 EPUB 文件"""
        path = file_path or self.file_path
        
        # TODO: 实现 EPUB 解析逻辑
        # 使用 zipfile 解压 + BeautifulSoup 解析 HTML
        
        return Book(
            id=Path(path).stem,
            title="",
            author="",
            path=path,
            format='epub',
            total_pages=0
        )
    
    def get_page(self, page_num: int) -> Page:
        """获取指定页内容"""
        # TODO: 实现分页逻辑
        return Page(page_num=page_num, content="")
    
    def get_total_pages(self) -> int:
        """获取总页数"""
        return len(self._chapters)


class PDFParser(BookParser):
    """PDF 文件解析器"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._texts = []
    
    def parse(self, file_path: str = None) -> Book:
        """解析 PDF 文件"""
        path = file_path or self.file_path
        
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            
            # 提取所有页面文本
            self._texts = []
            for page in reader.pages:
                text = page.extract_text()
                # 修复单字符换行问题
                if self._is_vertical_layout(text):
                    text = self._reconstruct_text(text)
                self._texts.append(text)
            
            # 提取元数据
            info = reader.metadata
            title = info.title if info and info.title else Path(path).stem
            author = info.author if info and info.author else ""
            
            return Book(
                id=Path(path).stem,
                title=title,
                author=author,
                path=path,
                format='pdf',
                total_pages=len(self._texts)
            )
        except Exception as e:
            print(f"PDF 解析失败: {e}")
            return Book(
                id=Path(path).stem,
                title=Path(path).stem,
                author="",
                path=path,
                format='pdf',
                total_pages=0
            )
    
    def _is_vertical_layout(self, text: str) -> bool:
        """检测是否为竖排文本（单字符换行）"""
        lines = text.split('\n')
        single_char_lines = sum(1 for line in lines if len(line.strip()) <= 2)
        return single_char_lines > len(lines) * 0.7
    
    def _reconstruct_text(self, text: str) -> str:
        """重建被错误换行的文本"""
        lines = text.split('\n')
        merged = ''.join(line.strip() for line in lines)
        
        # 在句子边界添加段落分隔
        import re
        result = re.sub(r'([。！？])\s*', r'\1\n', merged)
        return result
    
    def get_page(self, page_num: int) -> Page:
        """获取指定页内容"""
        if 0 <= page_num < len(self._texts):
            return Page(
                page_num=page_num,
                content=self._texts[page_num]
            )
        raise IndexError(f"Page {page_num} out of range")
    
    def get_total_pages(self) -> int:
        """获取总页数"""
        return len(self._texts)


class BookRepository:
    """书籍仓库 - 管理书籍列表和阅读进度"""
    
    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or "bookshelf.json"
        self.books: List[Book] = []
        self._load()
    
    def add_book(self, book: Book):
        """添加书籍"""
        self.books.append(book)
        self._save()
    
    def remove_book(self, book_id: str):
        """移除书籍"""
        self.books = [b for b in self.books if b.id != book_id]
        self._save()
    
    def get_book(self, book_id: str) -> Optional[Book]:
        """获取指定书籍"""
        for book in self.books:
            if book.id == book_id:
                return book
        return None
    
    def update_progress(self, book_id: str, current_page: int):
        """更新阅读进度"""
        book = self.get_book(book_id)
        if book:
            book.current_page = current_page
            self._save()
    
    def add_bookmark(self, book_id: str, page_num: int):
        """添加书签"""
        book = self.get_book(book_id)
        if book and page_num not in book.bookmarks:
            book.bookmarks.append(page_num)
            self._save()
    
    def _save(self):
        """保存书籍列表到文件"""
        data = [
            {
                'id': b.id,
                'title': b.title,
                'author': b.author,
                'path': b.path,
                'format': b.format,
                'total_pages': b.total_pages,
                'current_page': b.current_page,
                'bookmarks': b.bookmarks
            }
            for b in self.books
        ]
        
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load(self):
        """从文件加载书籍列表"""
        if not Path(self.storage_path).exists():
            return
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.books = [
                Book(
                    id=item['id'],
                    title=item['title'],
                    author=item.get('author', ''),
                    path=item['path'],
                    format=item['format'],
                    total_pages=item['total_pages'],
                    current_page=item.get('current_page', 0),
                    bookmarks=item.get('bookmarks', [])
                )
                for item in data
            ]
        except Exception as e:
            print(f"加载书籍列表失败: {e}")
            self.books = []


def create_parser(file_path: str) -> BookParser:
    """工厂函数 - 根据文件类型创建对应的解析器"""
    path = Path(file_path)
    suffix = path.suffix.lower()
    
    if suffix == '.txt':
        return TXTParser(file_path)
    elif suffix == '.epub':
        return EPUBParser(file_path)
    elif suffix == '.pdf':
        return PDFParser(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}")


__all__ = [
    'Book', 'Page', 'BookParser',
    'TXTParser', 'EPUBParser', 'PDFParser',
    'BookRepository', 'create_parser'
]
