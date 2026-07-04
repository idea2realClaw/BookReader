import flet as ft
import asyncio
import threading
import json
import os
import re
from reader import open_book, BookReader

BOOKS_JSON_PATH = os.path.expanduser("~/.bookreader/books.json")


class BookViewer(ft.Container):
    """Single-page book viewer with TTS read-aloud support."""

    def __init__(self, reader: BookReader, main_window, on_close=None):
        super().__init__(expand=True)
        self.reader = reader
        self.main_window = main_window
        self.ft_page = main_window.ft_page
        self.on_close = on_close
        self.current = 0
        self._is_reading = False
        self._tts_stop_event = threading.Event()
        self._current_sentence_idx = -1
        self._sentence_controls = []
        self._tts_engine = None
        self._tts_process = None  # 保存TTS进程

        # 页面文本容器（按句子显示，支持高亮）
        self.page_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=5,
        )

        self.page_label = ft.Text(size=12, color=ft.Colors.BLACK54)

        # 朗读按钮
        self.read_btn = ft.IconButton(
            ft.Icons.PLAY_ARROW,
            tooltip="朗读全书",
            icon_color=ft.Colors.BLUE,
            on_click=self._toggle_read,
        )

        self.header = ft.Row(
            [
                ft.IconButton(ft.Icons.ARROW_BACK, on_click=self._close),
                ft.Column(
                    [
                        ft.Text(
                            self.reader.metadata.title,
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLACK87,
                        ),
                        ft.Text(
                            self.reader.metadata.author,
                            size=12,
                            color=ft.Colors.BLACK54,
                        ),
                    ],
                    spacing=0,
                    expand=True,
                ),
                ft.IconButton(ft.Icons.MENU, on_click=self._show_jump_dialog),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self.content = ft.Column(
            [
                self.header,
                ft.Container(
                    content=self.page_column,
                    expand=True,
                    padding=ft.Padding(left=80, top=30, right=80, bottom=30),
                ),
                ft.Row(
                    [
                        ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self.prev_page, icon_size=40),
                        self.read_btn,
                        ft.Container(content=self.page_label, alignment=ft.Alignment.CENTER, expand=True),
                        ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self.next_page, icon_size=40),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=0,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
        )

        # 加载保存的位置
        self._load_position()
        self._update_page_display()
        self.ft_page.on_resize = self._on_resize

    def _split_into_sentences(self, text: str):
        """将文本分割成句子"""
        if not text:
            return []
        sentences = re.split(r'(?<=[。！？\.\!\?])\s*', text)
        return [s.strip() for s in sentences if s.strip()]

    def _update_page_display(self):
        """更新页面显示（按句子分割以支持高亮）"""
        text = self.reader.get_page(self.current)
        sentences = self._split_into_sentences(text)

        # 创建句子控件
        self._sentence_controls = []
        self.page_column.controls.clear()

        for sentence in sentences:
            text_control = ft.Text(
                sentence,
                size=self._get_font_size(),
                color=ft.Colors.BLACK87,
                selectable=True,
            )
            self._sentence_controls.append(text_control)
            self.page_column.controls.append(text_control)

        self.page_label.value = f"第 {self.current + 1} / {self.reader.get_page_count()} 页"
        self.ft_page.update()

    def _get_font_size(self):
        """获取当前字体大小"""
        width = self.ft_page.width or 1400
        if width > 1400:
            return 28
        elif width > 1200:
            return 24
        elif width > 900:
            return 20
        else:
            return 18

    def _update_font_size(self):
        """根据页面宽度调整字体大小"""
        new_size = self._get_font_size()
        for control in self._sentence_controls:
            control.size = new_size
        self.ft_page.update()

    async def _highlight_sentence(self, idx: int):
        """高亮指定句子（灰色背景）"""
        # 清除之前的高亮
        if 0 <= self._current_sentence_idx < len(self._sentence_controls):
            self._sentence_controls[self._current_sentence_idx].bgcolor = None

        # 高亮当前句子
        if 0 <= idx < len(self._sentence_controls):
            self._sentence_controls[idx].bgcolor = ft.Colors.GREY_300
            self._current_sentence_idx = idx
            # 滚动到当前句子
            self.page_column.scroll_to(delta=100)
            self.ft_page.update()

    async def _clear_highlight(self):
        """清除所有高亮"""
        for control in self._sentence_controls:
            control.bgcolor = None
        self._current_sentence_idx = -1
        self.ft_page.update()

    async def _close(self, e):
        """关闭阅读器，保存位置"""
        # 停止朗读
        if self._is_reading:
            self._tts_stop_event.set()
            self._is_reading = False

        # 保存阅读位置
        self._save_position()

        if self.on_close:
            await self.on_close()

    def _show_jump_dialog(self, e):
        total = self.reader.get_page_count()
        input_field = ft.TextField(label=f"页码 (1-{total})", keyboard_type=ft.KeyboardType.NUMBER)

        def jump(e):
            try:
                idx = int(input_field.value) - 1
                if 0 <= idx < total:
                    self.current = idx
                    self._update_page_display()
                dialog.open = False
                self.ft_page.update()
            except ValueError:
                pass

        dialog = ft.AlertDialog(
            title=ft.Text("跳转到页"),
            content=input_field,
            actions=[ft.TextButton("取消", on_click=lambda e: setattr(dialog, "open", False) or self.ft_page.update()), ft.TextButton("跳转", on_click=jump)],
        )
        self.ft_page.dialog = dialog
        dialog.open = True
        self.ft_page.update()

    async def next_page(self, e):
        if self.current < self.reader.get_page_count() - 1:
            self.current += 1
            await self._clear_highlight()
            self._update_page_display()

    async def prev_page(self, e):
        if self.current > 0:
            self.current -= 1
            await self._clear_highlight()
            self._update_page_display()

    def _on_resize(self, e):
        self._update_font_size()
        self.ft_page.update()

    async def _toggle_read(self, e):
        """切换朗读状态"""
        if self._is_reading:
            # 停止朗读
            self._tts_stop_event.set()
            self._is_reading = False
            self.read_btn.icon = ft.Icons.PLAY_ARROW
            self.read_btn.tooltip = "朗读全书"
            await self._clear_highlight()
            self.ft_page.update()
            print(f"[BookViewer] 停止朗读")
        else:
            # 开始朗读
            self._tts_stop_event.clear()
            self._is_reading = True
            self.read_btn.icon = ft.Icons.STOP_CIRCLE
            self.read_btn.tooltip = "停止朗读"
            self.ft_page.update()
            print(f"[BookViewer] 开始朗读")

            # 在后台任务中朗读
            asyncio.create_task(self._read_all())

    async def _read_all(self):
        """从当前页开始朗读，自动翻页"""
        while self._is_reading and not self._tts_stop_event.is_set():
            try:
                # 获取当前页文本
                text = self.reader.get_page(self.current)

                if not text:
                    print(f"[BookViewer] 第{self.current+1}页无文本，跳过")
                    if self.current < self.reader.get_page_count() - 1:
                        self.current += 1
                        self._update_page_display()
                        continue
                    else:
                        break

                print(f"[BookViewer] 朗读第{self.current+1}页")

                # 按句子朗读
                sentences = self._split_into_sentences(text)
                for i, sentence in enumerate(sentences):
                    if self._tts_stop_event.is_set():
                        print(f"[BookViewer] 朗读被停止")
                        break

                    # 高亮当前句子
                    await self._highlight_sentence(i)

                    # 朗读当前句子
                    await self._speak_text(sentence)

                if self._tts_stop_event.is_set():
                    break

                # 自动翻页
                if self.current < self.reader.get_page_count() - 1:
                    self.current += 1
                    await self._clear_highlight()
                    self._update_page_display()
                    print(f"[BookViewer] 自动翻到第{self.current+1}页")
                else:
                    # 已到最后一页
                    print(f"[BookViewer] 已到最后一页，停止朗读")
                    break

            except Exception as ex:
                print(f"[BookViewer] 朗读错误: {ex}")
                import traceback
                traceback.print_exc()
                break

        # 朗读结束，恢复按钮状态
        self._is_reading = False
        self._tts_stop_event.clear()
        self.read_btn.icon = ft.Icons.PLAY_ARROW
        self.read_btn.tooltip = "朗读全书"
        await self._clear_highlight()
        self.ft_page.update()
        print(f"[BookViewer] 朗读结束")

        # 保存阅读位置
        self._save_position()

    async def _speak_text(self, text: str):
        """使用TTS朗读文本（支持停止）"""
        if not text:
            return

        print(f"[BookViewer] TTS朗读: {len(text)} 字符")

        if self.ft_page.web:
            # 浏览器模式：使用Web Speech API
            await asyncio.sleep(len(text) / 10)  # 模拟朗读时间
        else:
            # 桌面模式：使用独立进程运行TTS（避免崩溃）
            try:
                await asyncio.to_thread(self._speak_with_process, text)
            except Exception as ex:
                print(f"[BookViewer] TTS错误: {ex}")
                await asyncio.sleep(1)

    def _speak_with_process(self, text: str):
        """使用独立进程朗读（支持停止）"""
        try:
            import subprocess
            import tempfile
            import os
            import time

            # 限制文本长度
            text = text[:200]

            # 创建VBScript
            vbs_script = f'''Set speak = CreateObject("SAPI.SpVoice")
speak.Rate = 2
speak.Speak "{text.replace(chr(34), "'").replace(chr(10), " ").replace(chr(13), " ")}"
'''

            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.vbs', encoding='ansi') as f:
                f.write(vbs_script)
                vbs_path = f.name

            # 启动进程
            self._tts_process = subprocess.Popen(
                ['cscript', '//nologo', vbs_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # 等待进程完成或停止事件
            while self._tts_process.poll() is None:
                if self._tts_stop_event.is_set():
                    print(f"[BookViewer] 停止TTS进程")
                    self._tts_process.terminate()
                    try:
                        self._tts_process.wait(timeout=1)
                    except:
                        self._tts_process.kill()
                    break
                time.sleep(0.1)

            # 清理临时文件
            try:
                os.unlink(vbs_path)
            except:
                pass

            self._tts_process = None

        except Exception as e:
            print(f"[BookViewer] TTS进程错误: {e}")
            import traceback
            traceback.print_exc()



    def _save_position(self):
        """保存当前阅读位置到本地"""
        try:
            os.makedirs(os.path.dirname(BOOKS_JSON_PATH), exist_ok=True)

            if os.path.exists(BOOKS_JSON_PATH):
                with open(BOOKS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"books": []}

            # 获取当前书籍路径
            book_path = ""
            if hasattr(self.reader, 'file_path'):
                book_path = self.reader.file_path
            elif hasattr(self.reader, '_file_path'):
                book_path = self.reader._file_path

            if not book_path:
                print(f"[BookViewer] 无法获取书籍路径，跳过保存位置")
                return

            # 更新当前书籍的位置
            found = False
            for book in data["books"]:
                if book["path"] == book_path:
                    book["last_page"] = self.current
                    found = True
                    break

            if not found:
                data["books"].append({
                    "path": book_path,
                    "title": self.reader.metadata.title,
                    "author": self.reader.metadata.author,
                    "pages": self.reader.get_page_count(),
                    "last_page": self.current,
                })

            with open(BOOKS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[BookViewer] 已保存阅读位置: 第{self.current+1}页")
        except Exception as e:
            print(f"[BookViewer] 保存位置失败: {e}")

    def _load_position(self):
        """从本地加载保存的阅读位置"""
        try:
            if os.path.exists(BOOKS_JSON_PATH):
                with open(BOOKS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)

            # 获取当前书籍路径
            book_path = ""
            if hasattr(self.reader, 'file_path'):
                book_path = self.reader.file_path
            elif hasattr(self.reader, '_file_path'):
                book_path = self.reader._file_path

            if not book_path:
                return

            for book in data["books"]:
                if book["path"] == book_path:
                    if "last_page" in book and book["last_page"] < self.reader.get_page_count():
                        self.current = book["last_page"]
                        print(f"[BookViewer] 已加载阅读位置: 第{self.current+1}页")
                    break
        except Exception as e:
            print(f"[BookViewer] 加载位置失败: {e}")
