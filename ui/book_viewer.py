import flet as ft
import asyncio
import threading
import json
import os
import re
from reader import open_book, BookReader
from ui.tts import TTSEngine, estimate_duration

BOOKS_JSON_PATH = os.path.expanduser("~/.bookreader/books.json")


class BookViewer(ft.Container):
    """Single-page book viewer with TTS read-aloud support.

    布局要点（满足"按窗口大小分页、无滚动条、一页一页翻"）：
    - 书籍打开时按当前窗口尺寸把整本文本动态切成"可视页"，每页正好填满
      文本区且不溢出 → 用单个 ft.Text(spans=...) 渲染，无滚动条。
    - 窗口尺寸变化（on_resize）时重新分页，并尽量保留当前阅读进度。
    - 翻页键（上/下）与朗读键、倍速滑块在底部一栏，钉在浮动日志上方。
    """

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
        self._page_sentences = []
        self._tts_engine = None
        self._tts_process = None
        self.tts = TTSEngine(self.ft_page)  # 跨平台 TTS 引擎
        self.tts.speed = 1.2  # 默认 1.2 倍速

        # 整本文本（用于按窗口动态分页）
        self.full_text = self.reader.get_full_text()
        self.pages: list = []
        self._page_chars = 600  # 每页字符数（动态计算）
        self._log_gap = 40  # 当前日志窗口高度（折叠默认 40）

        # 页面文本：单个 ft.Text，用 spans 实现逐句高亮；无滚动条
        self.page_text = ft.Text(
            size=self._get_font_size(),
            color=ft.Colors.BLACK87,
            selectable=True,
            no_wrap=False,
        )

        self.page_label = ft.Text(size=12, color=ft.Colors.BLACK54)

        # 朗读按钮
        self.read_btn = ft.IconButton(
            ft.Icons.PLAY_ARROW,
            tooltip="朗读全书",
            icon_color=ft.Colors.BLUE,
            on_click=self._toggle_read,
        )

        # 倍速滑块（播放键右侧）：1.0x ~ 2.0x，默认 1.2x
        self.speed_label = ft.Text("1.2x", size=12, color=ft.Colors.BLACK54, width=42)
        self.speed_slider = ft.Slider(
            min=1,
            max=2,
            value=1.2,
            divisions=40,
            width=130,
            tooltip="朗读倍速",
            on_change=self._on_speed,
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

        # 翻页/朗读/倍速栏：用 Stack 绝对定位，钉在浮动日志窗口上方（避免被日志盖住）
        self.nav_row = ft.Row(
            [
                ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self.prev_page, icon_size=40),
                self.read_btn,
                self.speed_slider,
                self.speed_label,
                ft.Container(content=self.page_label, alignment=ft.Alignment.CENTER, expand=True),
                ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self.next_page, icon_size=40),
            ],
            alignment=ft.MainAxisAlignment.START,
            height=56,
        )
        # flet 0.85.3：直接给 Stack 子控件设 left/right/bottom 定位（无 Positioned 包装类）
        self.nav_row.left = 0
        self.nav_row.right = 0
        self.nav_row.bottom = 10  # 初始值，set_log_gap 会更新为 gap + 10

        # 文本区：上下左右贴边；底部预留出 nav_row + 日志高度，避免被遮挡或过长
        self.text_container = ft.Container(
            content=self.page_text,
            padding=ft.Padding(left=80, top=30, right=80, bottom=30),
        )
        self.text_container.top = 0
        self.text_container.left = 0
        self.text_container.right = 0
        self.text_container.bottom = 70  # 初始值，set_log_gap 会更新

        # 阅读区主体：header 在顶部固定，body 为 Stack（文本层 + 浮动的翻页/朗读/倍速栏）
        self.body = ft.Stack(expand=True)
        self.body.controls = [self.text_container, self.nav_row]

        self.content = ft.Column(
            [
                self.header,
                self.body,
            ],
            spacing=0,
            expand=True,
        )

        # 加载保存的位置（仅作进度近似，动态分页后索引会按字符偏移重算）
        self._load_position()
        # 按窗口尺寸动态分页并渲染首屏
        self._recompute_layout(preserve=True)
        self.ft_page.on_resize = self._on_resize

    # ------------------------------------------------------------------
    # 动态分页
    # ------------------------------------------------------------------
    def _compute_page_chars(self) -> int:
        """根据窗口尺寸估算每页可容纳的字符数（保守取值，保证不溢出）。"""
        fs = self._get_font_size()
        w = self.ft_page.width or 1400
        h = self.ft_page.height or 800
        gap = self._log_gap
        header_h = 56
        pad_v = 100  # page.padding 上下各 50
        # 文本区可用高度 = 屏幕高 - 页面padding - header - 底部 nav+日志预留 - 文本容器内边距
        text_avail_h = h - pad_v - header_h - (gap + 82) - 60
        text_avail_w = w - 160  # 文本容器内边距左右各 80
        # 中文字符宽约 font_size；拉丁字符更窄，按 font_size 估算为保守下界（不会溢出）
        cpl = max(1, int(text_avail_w / fs * 0.95))      # 每行字符数
        lpp = max(1, int(text_avail_h / (fs * 1.5) * 0.9))  # 每页行数
        return max(1, cpl * lpp)

    def _recompute_layout(self, preserve=True):
        """按当前窗口尺寸重新分页；preserve=True 时尽量保留当前阅读进度。"""
        offset = self.current * self._page_chars if (preserve and self.pages) else 0
        page_chars = self._compute_page_chars()
        self._page_chars = page_chars
        full = self.full_text
        self.pages = [full[i: i + page_chars] for i in range(0, len(full), page_chars)] or [""]
        if preserve:
            self.current = min(max(offset // page_chars, 0), len(self.pages) - 1)
        else:
            self.current = 0
        self._update_page_display()

    def set_log_gap(self, gap: int):
        """把翻页/朗读/倍速栏钉在浮动日志窗口上方 10px（gap = 当前日志窗口高度）。

        使用 Stack 绝对定位（flet 0.85.3 给子控件设 left/right/bottom）：
        - nav_row.bottom = gap + 10  → 整排按钮完全位于日志顶边之上 10px，
          不再进入日志的覆盖区（之前用列 padding 会让按钮下半截被日志盖住）。
        - text_container.bottom = gap + 10 + nav 高度 + 余量 → 文本区下移，
          既不钻到按钮下面，也不会因日志展开而过长。
        日志展开/折叠时 MainWindow 会回调此方法更新位置，并随之重分页。
        """
        nav_height = 56
        self._log_gap = gap
        self.nav_row.bottom = gap + 10
        self.text_container.bottom = gap + 10 + nav_height + 16  # +16 为安全余量
        self.nav_row.left = 0
        self.nav_row.right = 0
        self.text_container.left = 0
        self.text_container.right = 0
        self.text_container.top = 0
        # 日志高度变化会改变可用文本高度 → 重新分页以适配
        try:
            self._recompute_layout(preserve=True)
        except Exception:
            try:
                self.ft_page.update()
            except Exception:
                pass

    def _split_into_sentences(self, text: str):
        """将文本分割成句子（保留句末标点）。"""
        if not text:
            return []
        sentences = re.split(r'(?<=[。！？\.\!\?])\s*', text)
        return [s.strip() for s in sentences if s.strip()]

    def _render_spans(self, highlight_idx=-1):
        """用 TextSpan 渲染当前页；highlight_idx 指定的句子加灰色背景。"""
        text = self.pages[self.current]
        sentences = self._split_into_sentences(text)
        self._page_sentences = sentences
        fs = self._get_font_size()
        spans = []
        for i, s in enumerate(sentences):
            bg = ft.Colors.GREY_300 if i == highlight_idx else None
            spans.append(
                ft.TextSpan(
                    text=s,
                    style=ft.TextStyle(size=fs, color=ft.Colors.BLACK87, bgcolor=bg),
                )
            )
        self.page_text.spans = spans
        self.page_text.value = None

    def _update_page_display(self):
        """更新页面显示（按句子分割以支持高亮，无滚动条）。"""
        if not self.pages:
            self.pages = [""]
        self._render_spans(-1)
        self.page_label.value = f"第 {self.current + 1} / {len(self.pages)} 页"
        self.ft_page.update()

    def _get_font_size(self):
        """根据页面宽度选择字号。"""
        width = self.ft_page.width or 1400
        if width > 1400:
            return 28
        elif width > 1200:
            return 24
        elif width > 900:
            return 20
        else:
            return 18

    async def _highlight_sentence(self, idx: int):
        """高亮指定句子（灰色背景）。"""
        if 0 <= idx < len(self._page_sentences):
            self._current_sentence_idx = idx
            self._render_spans(idx)
            self.ft_page.update()

    async def _clear_highlight(self):
        """清除所有高亮。"""
        self._current_sentence_idx = -1
        self._render_spans(-1)
        self.ft_page.update()

    async def _close(self, e):
        """关闭阅读器，保存位置。"""
        if self._is_reading:
            self._tts_stop_event.set()
            self._is_reading = False
            try:
                self.tts.stop()
            except Exception:
                pass

        self._save_position()

        if self.on_close:
            await self.on_close()

    def _show_jump_dialog(self, e):
        total = len(self.pages)
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
        if self.current < len(self.pages) - 1:
            self.current += 1
            await self._clear_highlight()
            self._update_page_display()

    async def prev_page(self, e):
        if self.current > 0:
            self.current -= 1
            await self._clear_highlight()
            self._update_page_display()

    def _on_resize(self, e):
        # 窗口变化：重新分页（字号/每页字符数随之调整，并保留进度）
        self._recompute_layout(preserve=True)

    def _on_speed(self, e):
        """倍速滑块：更新 TTS 倍速与标签（下一次朗读生效；桌面端即时作用于语速）。"""
        v = float(e.control.value)
        self.tts.speed = v
        self.speed_label.value = f"{v:.1f}x"
        self.ft_page.update()

    async def _toggle_read(self, e):
        """切换朗读状态。"""
        if self._is_reading:
            # 停止朗读
            self._tts_stop_event.set()
            self._is_reading = False
            try:
                self.tts.stop()
            except Exception:
                pass
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

    async def _wait_for(self, seconds: float):
        """等待 seconds 秒，但随时可被停止事件中断。"""
        step = 0.1
        elapsed = 0.0
        while elapsed < seconds and not self._tts_stop_event.is_set():
            await asyncio.sleep(step)
            elapsed += step

    async def _read_all(self):
        """从当前页开始朗读，自动翻页。"""
        while self._is_reading and not self._tts_stop_event.is_set():
            try:
                # 获取当前页文本（窗口分页后的可视页）
                text = self.pages[self.current]

                if not text.strip():
                    print(f"[BookViewer] 第{self.current + 1}页无文本，跳过")
                    if self.current < len(self.pages) - 1:
                        self.current += 1
                        self._update_page_display()
                        continue
                    else:
                        break

                print(f"[BookViewer] 朗读第{self.current + 1}页")

                # 按句子拆分（用于逐句高亮）
                sentences = self._split_into_sentences(text)
                durations = [estimate_duration(s) for s in sentences]

                # 整页一次性朗读（安卓端只会触发一次系统播放器，避免每句弹窗）
                speak_task = asyncio.create_task(self._speak_text(text))

                # 按估算时长逐句高亮，与朗读节奏大致同步
                for i, d in enumerate(durations):
                    if self._tts_stop_event.is_set():
                        break
                    await self._highlight_sentence(i)
                    await self._wait_for(d)

                # 等待整页朗读结束
                try:
                    await speak_task
                except Exception as ex:
                    print(f"[BookViewer] 朗读任务异常: {ex}")

                if self._tts_stop_event.is_set():
                    break

                # 自动翻页
                if self.current < len(self.pages) - 1:
                    self.current += 1
                    await self._clear_highlight()
                    self._update_page_display()
                    print(f"[BookViewer] 自动翻到第{self.current + 1}页")
                else:
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
        """使用跨平台 TTS 朗读文本（支持停止）。"""
        if not text.strip():
            return

        print(f"[BookViewer] TTS朗读: {len(text)} 字符")
        try:
            await self.tts.speak(text, self._tts_stop_event)
        except Exception as ex:
            print(f"[BookViewer] TTS错误: {ex}")
            import traceback
            traceback.print_exc()

    def _save_position(self):
        """保存当前阅读位置到本地。"""
        try:
            os.makedirs(os.path.dirname(BOOKS_JSON_PATH), exist_ok=True)

            if os.path.exists(BOOKS_JSON_PATH):
                with open(BOOKS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"books": []}

            book_path = ""
            if hasattr(self.reader, 'file_path'):
                book_path = self.reader.file_path
            elif hasattr(self.reader, '_file_path'):
                book_path = self.reader._file_path

            if not book_path:
                print(f"[BookViewer] 无法获取书籍路径，跳过保存位置")
                return

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
                    "pages": len(self.pages),
                    "last_page": self.current,
                })

            with open(BOOKS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[BookViewer] 已保存阅读位置: 第{self.current + 1}页")
        except Exception as e:
            print(f"[BookViewer] 保存位置失败: {e}")

    def _load_position(self):
        """从本地加载保存的阅读位置（动态分页后按字符偏移近似恢复）。"""
        try:
            if not os.path.exists(BOOKS_JSON_PATH):
                return

            with open(BOOKS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            book_path = ""
            if hasattr(self.reader, 'file_path'):
                book_path = self.reader.file_path
            elif hasattr(self.reader, '_file_path'):
                book_path = self.reader._file_path

            if not book_path:
                return

            for book in data["books"]:
                if book["path"] == book_path:
                    if "last_page" in book:
                        self.current = book["last_page"]
                        print(f"[BookViewer] 已加载阅读位置: 第{self.current + 1}页（近似值）")
                    break
        except Exception as e:
            print(f"[BookViewer] 加载位置失败: {e}")
