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
        
        # 检测并修复竖排文本（每行只有1-2个字符的情况）
        lines = text.split('\n')
        if len(lines) > 10:  # 至少10行才检测
            avg_len = sum(len(l.strip()) for l in lines) / len(lines)
            
            # 如果平均每行少于4个字符，认为是竖排
            if avg_len < 4:
                # 重新格式化：合并所有行，保留段落分隔
                formatted = self._fix_vertical_text(lines)
                return formatted
        
        return text

    def _fix_vertical_text(self, lines: list) -> str:
        """修复竖排文本，将单行单字的格式转为正常段落"""
        result = []
        current_line = []
        
        for line in lines:
            stripped = line.strip()
            
            # 跳过空行
            if not stripped:
                if current_line:
                    # 合并当前段落
                    paragraph = ''.join(current_line)
                    # 移除中文字符间的空格
                    paragraph = self._remove_spaces_between_chinese(paragraph)
                    result.append(paragraph)
                    current_line = []
                result.append('')  # 保留段落分隔
                continue
            
            # 如果这行只有1-2个字符（可能是竖排）
            if len(stripped) <= 2:
                # 移除空格后添加
                current_line.append(stripped.replace(' ', ''))
            else:
                # 正常长度的文本，直接添加
                if current_line:
                    paragraph = ''.join(current_line)
                    paragraph = self._remove_spaces_between_chinese(paragraph)
                    result.append(paragraph)
                    current_line = []
                result.append(stripped)
        
        # 添加最后一行
        if current_line:
            paragraph = ''.join(current_line)
            paragraph = self._remove_spaces_between_chinese(paragraph)
            result.append(paragraph)
        
        return '\n'.join(result)
    
    def _remove_spaces_between_chinese(self, text: str) -> str:
        """移除中文字符之间的空格"""
        import re
        # 匹配中文之间的空格并移除
        # 保留英文单词之间的空格
        result = []
        i = 0
        chars = list(text)
        
        while i < len(chars):
            if i + 1 < len(chars):
                # 如果当前字符和下一个字符都是中文，且中间有空格
                if (self._is_chinese(chars[i]) and 
                    self._is_chinese(chars[i+1]) and 
                    chars[i+1] == ' '):
                    result.append(chars[i])
                    i += 2  # 跳过空格
                    continue
            result.append(chars[i])
            i += 1
        
        return ''.join(result)
    
    def _is_chinese(self, char: str) -> bool:
        """判断字符是否是中文"""
        if not char:
            return False
        cp = ord(char)
        # 中文Unicode范围
        return (0x4E00 <= cp <= 0x9FFF or  # CJK统一汉字
                0x3400 <= cp <= 0x4DBF or  # CJK统一汉字扩展A
                0x20000 <= cp <= 0x2A6DF)  # CJK统一汉字扩展B
