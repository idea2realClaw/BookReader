import flet as ft
import asyncio
import functools
import threading
import json
import os
import re
from reader import open_book, BookReader
from ui.tts import TTSEngine, estimate_duration

BOOKS_JSON_PATH = os.path.expanduser("~/.bookreader/books.json")

# 句子切分正则：保留句末标点（中英文），并记录每个句子在原文本中的起始偏移。
# 形如 "你好。世界" -> [("你好。", 0), ("世界", 3)]
_SENT_RE = re.compile(r'\s*([^。！？\.\!\?]+[。！？\.\!\?]?)')


class BookViewer(ft.Container):
    """Single-page book viewer with TTS read-aloud support.

    布局要点（满足"按窗口大小分页、无滚动条、一页一页翻"）：
    - 书籍打开时按当前窗口尺寸把整本文本动态切成"可视页"，每页正好填满
      文本区且不溢出 → 用单个 ft.Text(spans=...) 渲染，无滚动条。
    - 窗口尺寸变化（on_resize）时重新分页，并尽量保留当前阅读进度。
    - 翻页键（上/下）与朗读键、倍速滑块在底部一栏，钉在浮动日志上方。

    朗读特性（v1.0.17）：
    - 点击页面中任意一句即可"从该句开始朗读"（selectable=False 以保证
      TextSpan.on_click 可靠触发；移动端为点按）。
    - 每读完一句把"绝对字符偏移"写入本地 books.json，下次打开书籍时按偏移
      精确恢复页码与句位，并自动从该句继续朗读。
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
        self._read_task = None            # 当前朗读任务（用于点击跳转时等待旧任务结束）
        self._last_read_offset = None     # 最近一次朗读到的绝对字符偏移（关闭时回退保存用）
        self._resume_char_offset = None   # 待恢复的字符偏移（__init__ 阶段由 _load_position 写入）
        self._pending_resume_sentence = None  # 重分页后计算出的"续读句下标"
        self.tts = TTSEngine(self.ft_page)  # 跨平台 TTS 引擎
        self.tts.speed = 1.2  # 默认 1.2 倍速

        # 整本文本（用于按窗口动态分页）
        self.full_text = self.reader.get_full_text()
        self.pages: list = []
        self._page_chars = 600  # 每页字符数（动态计算）
        self._log_gap = 40  # 当前日志窗口高度（折叠默认 40）

        # 页面文本：单个 ft.Text，用 spans 实现逐句高亮；无滚动条。
        # selectable=False 以确保 TextSpan.on_click（点击句子从该句朗读）可靠触发。
        self.page_text = ft.Text(
            size=self._get_font_size(),
            color=ft.Colors.BLACK87,
            selectable=False,
            no_wrap=False,
            tooltip="点击任意句子，即可从该句开始朗读",
        )

        self.page_label = ft.Text(size=12, color=ft.Colors.BLACK54)

        # 朗读按钮
        self.read_btn = ft.IconButton(
            ft.Icons.PLAY_ARROW,
            tooltip="朗读全书（点击句子可从该句开始）",
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

        # 小提示：点击句子即选朗读起点（浅灰、不抢眼）
        self.hint = ft.Text(
            "点击任意句子可从该句开始朗读，进度自动保存",
            size=11,
            color=ft.Colors.BLACK45,
            italic=True,
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
                self.hint,
                self.body,
            ],
            spacing=0,
            expand=True,
        )

        # 加载保存的位置（仅写入"待恢复字符偏移"，真正恢复在重分页时按窗口尺寸计算）
        self._load_position()
        # 按窗口尺寸动态分页并渲染首屏（会消费待恢复偏移，算出续读句下标）
        self._recompute_layout(preserve=True)
        self.ft_page.on_resize = self._on_resize

        # 若存在续读位置，打开即自动从该句继续朗读（在事件循环中调度，确保挂载后执行）
        if self._pending_resume_sentence is not None and self._pending_resume_sentence >= 0:
            asyncio.create_task(self._auto_resume())

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
        """按当前窗口尺寸重新分页；preserve=True 时尽量保留当前阅读进度。

        若有待恢复字符偏移（_resume_char_offset），则按绝对偏移精确恢复页码与续读句，
        保证不同窗口尺寸 / 不同会话之间"续读位置"一致。
        """
        if preserve and self._resume_char_offset is not None:
            page_chars = self._compute_page_chars()
            self._page_chars = page_chars
            full = self.full_text
            self.pages = [full[i: i + page_chars] for i in range(0, len(full), page_chars)] or [""]
            self.current = min(max(self._resume_char_offset // page_chars, 0), len(self.pages) - 1)
            self._pending_resume_sentence = self._sentence_index_at_offset(
                self.current, self._resume_char_offset
            )
            self._resume_char_offset = None  # 已消费
            highlight = self._pending_resume_sentence if self._pending_resume_sentence >= 0 else -1
            self._update_page_display(highlight=highlight)
            return

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
        """将文本分割成句子（保留句末标点），返回句子文本列表。"""
        return [s for s, _ in self._split_into_sentences_with_offsets(text)]

    def _split_into_sentences_with_offsets(self, text: str):
        """将文本分割成句子，返回 [(句子文本, 该句在原文中的起始偏移), ...]。"""
        if not text or not text.strip():
            return []
        res = []
        for m in _SENT_RE.finditer(text):
            s = m.group(1).strip()
            if s:
                res.append((s, m.start(1)))
        if not res:
            # 整段都没有终止标点时，按整段作为一句
            res.append((text.strip(), 0))
        return res

    def _sentence_index_at_offset(self, page_idx: int, global_offset: int) -> int:
        """根据绝对字符偏移，返回该页中应续读的句子下标。"""
        if not (0 <= page_idx < len(self.pages)):
            return 0
        local = global_offset - page_idx * self._page_chars
        sents = self._split_into_sentences_with_offsets(self.pages[page_idx])
        if not sents:
            return 0
        # 命中包含该偏移的句子
        for i, (s, off) in enumerate(sents):
            if off <= local < off + len(s):
                return i
        # 否则取第一个起始偏移 >= local 的句子
        for i, (s, off) in enumerate(sents):
            if off >= local:
                return i
        return len(sents) - 1

    def _render_spans(self, highlight_idx=-1):
        """用 TextSpan 渲染当前页；highlight_idx 指定的句子加灰色背景；每句可点击。"""
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
                    on_click=functools.partial(self._on_sentence_click, i),
                )
            )
        self.page_text.spans = spans
        self.page_text.value = None

    def _update_page_display(self, highlight=-1):
        """更新页面显示（按句子分割以支持高亮，无滚动条）。"""
        if not self.pages:
            self.pages = [""]
        self._render_spans(highlight)
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

    # ------------------------------------------------------------------
    # 点击句子选择朗读起点
    # ------------------------------------------------------------------
    def _on_sentence_click(self, idx, e):
        """句子被点击（on_click 为同步回调）：调度"从该句开始朗读"。"""
        asyncio.create_task(self._start_reading_from(idx))

    async def _start_reading_from(self, idx: int):
        """停止当前朗读（若有），并从指定句子开始朗读。"""
        if self._is_reading:
            # 先结束旧任务，避免两个朗读循环重叠
            self._tts_stop_event.set()
            if self._read_task is not None:
                try:
                    await self._read_task
                except Exception:
                    pass
        # 进入朗读状态，从该句开始
        self._tts_stop_event.clear()
        self._is_reading = True
        self.read_btn.icon = ft.Icons.STOP_CIRCLE
        self.read_btn.tooltip = "停止朗读"
        self.ft_page.update()
        self._read_task = asyncio.create_task(self._read_all(start_sentence=idx))

    async def _toggle_read(self, e):
        """切换朗读状态。

        未朗读时按"朗读全书"：从当前页第一句开始朗读。
        朗读中按停止：停止朗读。
        （点击任意句子则直接从该句开始，见 _start_reading_from）
        """
        if self._is_reading:
            # 停止朗读
            self._tts_stop_event.set()
            self._is_reading = False
            try:
                self.tts.stop()
            except Exception:
                pass
            self.read_btn.icon = ft.Icons.PLAY_ARROW
            self.read_btn.tooltip = "朗读全书（点击句子可从该句开始）"
            await self._clear_highlight()
            self.ft_page.update()
            print(f"[BookViewer] 停止朗读")
        else:
            # 开始朗读（当前页第一句）
            self._tts_stop_event.clear()
            self._is_reading = True
            self.read_btn.icon = ft.Icons.STOP_CIRCLE
            self.read_btn.tooltip = "停止朗读"
            self.ft_page.update()
            print(f"[BookViewer] 开始朗读")
            self._read_task = asyncio.create_task(self._read_all(start_sentence=0))

    async def _auto_resume(self):
        """打开书籍后：若存在续读位置，自动从该句继续朗读。"""
        if self._pending_resume_sentence is not None and self._pending_resume_sentence >= 0:
            start = self._pending_resume_sentence
            self._pending_resume_sentence = None
            # 进入朗读状态
            self._tts_stop_event.clear()
            self._is_reading = True
            self.read_btn.icon = ft.Icons.STOP_CIRCLE
            self.read_btn.tooltip = "停止朗读"
            self.ft_page.update()
            print(f"[BookViewer] 自动续读：从第{self.current + 1}页第{start + 1}句")
            self._read_task = asyncio.create_task(self._read_all(start_sentence=start))

    async def _wait_for(self, seconds: float):
        """等待 seconds 秒，但随时可被停止事件中断。"""
        step = 0.1
        elapsed = 0.0
        while elapsed < seconds and not self._tts_stop_event.is_set():
            await asyncio.sleep(step)
            elapsed += step

    async def _read_all(self, start_sentence=0):
        """从当前页的 start_sentence 句开始朗读，自动翻页；逐句记录位置。"""
        first_page = True
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

                # 按句子拆分（用于逐句高亮 + 记录位置），保留每句偏移
                sentences = self._split_into_sentences_with_offsets(text)
                if not sentences:
                    if self.current < len(self.pages) - 1:
                        self.current += 1
                        self._update_page_display()
                        continue
                    else:
                        break

                # 当前页起始的绝对字符偏移（用于换算续读位置）
                page_char_offset = self.current * self._page_chars

                start_idx = start_sentence if first_page else 0
                first_page = False

                if start_idx <= 0:
                    # 从本页第一句开始：整页一次性朗读（安卓端只触发一次系统播放器）
                    speak_text = text
                    local_base = 0
                else:
                    # 从选中句开始：拼接选中句及之后所有句；local_base 为选中句偏移
                    speak_text = text[sentences[start_idx][1]:]
                    local_base = sentences[start_idx][1]

                durations = [estimate_duration(s) for s, _ in sentences]

                # 整段一次性朗读（桌面端稳定；安卓端一次系统播放器）
                speak_task = asyncio.create_task(self._speak_text(speak_text))

                # 按估算时长逐句高亮，与朗读节奏大致同步；同时记录每句位置
                for i in range(start_idx, len(sentences)):
                    if self._tts_stop_event.is_set():
                        break
                    await self._highlight_sentence(i)
                    # 朗读到该句即记录"绝对字符偏移"，作为续读位置
                    global_off = page_char_offset + sentences[i][1]
                    self._save_position(global_off)
                    await self._wait_for(durations[i])

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
        self._read_task = None
        self.read_btn.icon = ft.Icons.PLAY_ARROW
        self.read_btn.tooltip = "朗读全书（点击句子可从该句开始）"
        await self._clear_highlight()
        self.ft_page.update()
        print(f"[BookViewer] 朗读结束")

        # 结束时再保存一次当前位置（兜底；读句中已逐句保存）
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

    def _save_position(self, global_offset=None):
        """保存当前阅读位置到本地（~/.bookreader/books.json）。

        global_offset：以整本 full_text 为基准的绝对字符偏移；
                       为 None 时优先用最近一次朗读到的偏移，否则用当前页起始偏移。
        以"绝对字符偏移"存储，保证不同窗口尺寸下都能精确恢复页码与句位。
        """
        try:
            # 计算实际要保存的偏移
            if global_offset is None:
                if self._last_read_offset is not None:
                    global_offset = self._last_read_offset
                else:
                    global_offset = self.current * self._page_chars
            else:
                self._last_read_offset = global_offset

            os.makedirs(os.path.dirname(BOOKS_JSON_PATH), exist_ok=True)

            if os.path.exists(BOOKS_JSON_PATH):
                with open(BOOKS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"books": []}

            # 兼容旧版顶层 list 格式，统一为 {"books": [...]}
            if isinstance(data, list):
                data = {"books": data}

            book_path = ""
            if hasattr(self.reader, "path"):
                book_path = self.reader.path
            if not book_path:
                print(f"[BookViewer] 无法获取书籍路径，跳过保存位置")
                return

            page_idx = global_offset // self._page_chars if self._page_chars else 0
            found = False
            for book in data["books"]:
                if book["path"] == book_path:
                    book["char_offset"] = global_offset
                    book["last_page"] = page_idx
                    book["pages"] = len(self.pages)
                    found = True
                    break

            if not found:
                data["books"].append({
                    "path": book_path,
                    "title": self.reader.metadata.title,
                    "author": self.reader.metadata.author,
                    "pages": len(self.pages),
                    "last_page": page_idx,
                    "char_offset": global_offset,
                })

            with open(BOOKS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[BookViewer] 已保存阅读位置: 字符偏移 {global_offset}（≈第{page_idx + 1}页）")
        except Exception as e:
            print(f"[BookViewer] 保存位置失败: {e}")

    def _load_position(self):
        """从本地加载保存的阅读位置（仅写入"待恢复字符偏移"，重分页时换算为页码+句位）。"""
        try:
            if not os.path.exists(BOOKS_JSON_PATH):
                return

            with open(BOOKS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 迁移：旧版把书籍直接存为顶层 list；新版本统一包在 {"books": [...]} 下。
            # 检测到旧格式时自动归一化并写回，避免丢失已有记录。
            if isinstance(data, list):
                data = {"books": data}
                try:
                    with open(BOOKS_JSON_PATH, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"[BookViewer] 已将旧版 books.json 迁移为新格式")
                except Exception:
                    pass

            # 防御：books.json 可能因旧版本/损坏而结构不符
            if not isinstance(data, dict) or not isinstance(data.get("books"), list):
                print(f"[BookViewer] books.json 结构不符，忽略旧位置")
                return

            book_path = ""
            if hasattr(self.reader, "path"):
                book_path = self.reader.path
            if not book_path:
                return

            for book in data["books"]:
                if not isinstance(book, dict):
                    continue
                if book["path"] == book_path:
                    if "char_offset" in book and book["char_offset"] is not None:
                        self._resume_char_offset = int(book["char_offset"])
                        print(f"[BookViewer] 已加载阅读位置: 字符偏移 {self._resume_char_offset}（打开即续读）")
                    elif "last_page" in book:
                        # 旧数据兜底：仅有页码时，从当页第一句续读
                        self._resume_char_offset = int(book["last_page"]) * (self._page_chars or 600)
                    break
        except Exception as e:
            print(f"[BookViewer] 加载位置失败: {e}")
