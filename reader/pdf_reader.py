import os
from pypdf import PdfReader as PyPdfReader
from .base import BookReader, BookMetadata


class PdfReader(BookReader):
    """PDF reader using pure-Python pypdf."""

    def __init__(self, path: str):
        super().__init__(path)
        self._doc = None

    def load(self) -> None:
        self._doc = PyPdfReader(self.path)
        title = os.path.splitext(os.path.basename(self.path))[0]
        # Try to extract title from metadata.
        meta = self._doc.metadata
        if meta and getattr(meta, "title", None):
            title = str(meta.title)
        self.metadata = BookMetadata(title=title, author="")

    def get_page_count(self) -> int:
        return len(self._doc.pages)

    def get_page(self, index: int) -> str:
        page = self._doc.pages[index]
        text = page.extract_text()
        
        if not text:
            return ""
        
        # 检测并修复"每个字符都换行"的问题
        lines = text.split('\n')
        if len(lines) > 20:  # 至少20行才检测
            # 统计每行长度
            short_lines = sum(1 for l in lines if len(l.strip()) <= 2)
            ratio = short_lines / len(lines)
            
            # 如果超过70%的行只有1-2个字符，说明是提取bug
            if ratio > 0.7:
                print(f"[PdfReader] 检测到文本提取异常（{ratio:.0%}的行只有1-2个字符），正在修复...")
                text = self._reconstruct_text(lines)
        
        return text

    def _reconstruct_text(self, lines: list) -> str:
        """重构文本：将每个字符一行的格式转为正常段落"""
        # 第一步：合并所有行
        all_chars = []
        for line in lines:
            stripped = line.strip()
            if stripped:
                all_chars.append(stripped)
        
        # 第二步：合并成完整文本
        full_text = ''.join(all_chars)
        
        # 第三步：使用启发式规则添加合理的换行
        import re
        
        # 在章节标题前添加双换行
        # 匹配：第X章、第X节、附录X、前言、序言、目录等
        text = re.sub(r'(第[一二三四五六七八九十\d]+[章节]|\n录[一二三四五六七八九十\d]+|前言|序言|目录|附录)', r'\n\n\1', full_text)
        
        # 在句号、问号、感叹号后添加换行（但不是段落结尾）
        # 先添加标记
        text = re.sub(r'([。！？\n])\s*', r'\1\n', text)
        
        # 清理：移除标题后的换行（标题应该单独一行）
        text = re.sub(r'(第[一二三四五六七八九十\d]+[章节].*?)\n', r'\1\n\n', text)
        
        # 清理多余的空行（最多保留一个空行）
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 移除行首行尾的空格
        text = '\n'.join(line.strip() for line in text.split('\n'))
        
        return text.strip()
