import flet as ft
import asyncio
import functools
import threading
import json
import os
import re
from reader import open_book, BookReader
from ui.tts import TTSEngine, estimate_duration
from paths import app_data_path

# 阅读位置持久化文件路径（与书架 shelf.json 分离，避免结构冲突互相覆盖）
# 跨平台：桌面=~/.bookreader/books.json，安卓=FLET_APP_STORAGE_DATA/books.json
# （不能直接用 os.path.expanduser('~/.bookreader/...') —— 安卓上 ~ 解析为 /data
# 会导致 /data/.bookreader Permission denied）
BOOKS_JSON_PATH = app_data_path("books.json")

# 句子切分正则：保留句末标点（中英文），并记录每个句子在原文本中的起始偏移。
# 形如 "你好。世界" -> [("你好。", 0), ("世界", 3)]
_SENT_RE = re.compile(r'\s*([^。！？\.\!\?]+[。！？\.\!\?]?)')

# 分页断页用的"句末标点"集合（页尾应落在此类标点上，使句子不被截断）。
_PAGE_BREAK_RE = re.compile(r"[。！？!?；;…\n]")


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
        self._restart_timer = None         # 调速防抖定时器（避免拖动时反复重启朗读）
        self._last_read_offset = None     # 最近一次朗读到的绝对字符偏移（关闭时回退保存用）
        self._resume_char_offset = None   # 待恢复的字符偏移（__init__ 阶段由 _load_position 写入）
        self._pending_resume_sentence = None  # 重分页后计算出的"续读句下标"
        self.tts = TTSEngine(self.ft_page)  # 跨平台 TTS 引擎
        self.tts.speed = 1.2  # 默认 1.2 倍速

        # 整本文本（用于按窗口动态分页）
        self.full_text = self.reader.get_full_text()
        self.pages: list = []
        self._page_start_offsets = []  # 每页在整本文本中的绝对起始偏移（变长分页用）
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
            on_change_end=self._on_speed_end,
        )

        # 音色下拉（倍速右侧）：男 / 女，缺省男
        self.voice_dd = ft.Dropdown(
            label="音色",
            value="male",
            width=110,
            text_size=12,
            options=[
                ft.dropdown.Option("male", "男声"),
                ft.dropdown.Option("female", "女声"),
            ],
            on_select=self._on_voice,
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
        # 布局：向前翻页键 + 播放键 + 滑块 + 标签 + 音色 靠左成组；page_label 用 expand
        # 占位把向后翻页键（CHEVRON_RIGHT）推到屏幕最右并保证其完整可见。
        self.prev_btn = ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self.prev_page, icon_size=40, tooltip="上一页")
        self.next_btn = ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=self.next_page, icon_size=40, tooltip="下一页")
        self.nav_row = ft.Row(
            [
                self.prev_btn,
                self.read_btn,
                self.speed_slider,
                self.speed_label,
                self.voice_dd,
                ft.Container(content=self.page_label, alignment=ft.Alignment.CENTER, expand=True),
                self.next_btn,
            ],
            alignment=ft.MainAxisAlignment.START,
            height=56,
        )
        # flet 0.85.3：直接给 Stack 子控件设 left/right/bottom 定位（无 Positioned 包装类）
        self.nav_row.left = 0
        self.nav_row.right = 0
        self.nav_row.bottom = 10  # 初始值，set_log_gap 会更新为 gap + 10

        # 按屏幕宽度响应化底部控制栏（滑块随屏宽缩短，确保最右翻页键不溢出）
        self._layout_nav()

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

        # 若存在续读位置，打开即把光标定位到该句并高亮，但不自动朗读
        # （按钮保持"播放"状态，由用户按下播放键时从该行继续）。
        if self._pending_resume_sentence is not None and self._pending_resume_sentence >= 0:
            asyncio.create_task(self._apply_resume_highlight())

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
        lpp = max(1, int(text_avail_h / (fs * 1.5) * 0.82))  # 每页行数（0.82 预留标点断句尾部余量）
        return max(1, cpl * lpp)

    # ------------------------------------------------------------------
    # 标点感知分页
    # ------------------------------------------------------------------
    def _paginate(self, full: str, page_chars: int):
        """按窗口尺寸把整本文本切成"可视页"。

        每页尽量在句末标点处断开（页尾最后一字为标点），使朗读/翻页不被句子
        截断；若从 page_chars 起向后一段范围内都没有标点（超长无标点句子），
        则在 page_chars 处硬切，避免无限搜索、也避免把整页撑得过长溢出。
        返回 (pages, starts)：pages 为每页文本，starts 为每页在整本文本中的
        绝对起始偏移（变长分页下用于精确换算续读位置）。
        """
        pages: list = []
        starts: list = []
        n = len(full)
        if page_chars < 1:
            page_chars = 1
        # 向后搜索标点的窗口上限：既保证句子尽量完整，又防止超长无标点句子时
        # 把整页撑得过长导致溢出。
        lookahead = min(page_chars, 150)
        pos = 0
        while pos < n:
            target = pos + page_chars
            if target >= n:
                pages.append(full[pos:])
                starts.append(pos)
                break
            seg = full[target: target + lookahead]
            m = _PAGE_BREAK_RE.search(seg)
            end = target + m.start() + 1 if m else target  # 包含标点；无标点则硬切
            if end <= pos:
                end = target
            pages.append(full[pos:end])
            starts.append(pos)
            pos = end
        if not pages:
            pages = [""]
            starts = [0]
        return pages, starts

    def _page_index_for_offset(self, offset: int) -> int:
        """返回包含 offset 的页码下标（基于实际页起始偏移二分查找）。"""
        starts = self._page_start_offsets
        if not starts:
            return 0
        if offset <= starts[0]:
            return 0
        if offset >= starts[-1]:
            return len(starts) - 1
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def _recompute_layout(self, preserve=True):
        """按当前窗口尺寸重新分页；preserve=True 时尽量保留当前阅读进度。

        若有待恢复字符偏移（_resume_char_offset），则按绝对偏移精确恢复页码与续读句，
        保证不同窗口尺寸 / 不同会话之间"续读位置"一致。
        """
        if preserve and self._resume_char_offset is not None:
            page_chars = self._compute_page_chars()
            self._page_chars = page_chars
            full = self.full_text
            self.pages, self._page_start_offsets = self._paginate(full, page_chars)
            self.current = self._page_index_for_offset(self._resume_char_offset)
            self._pending_resume_sentence = self._sentence_index_at_offset(
                self.current, self._resume_char_offset
            )
            self._resume_char_offset = None  # 已消费
            highlight = self._pending_resume_sentence if self._pending_resume_sentence >= 0 else -1
            self._update_page_display(highlight=highlight)
            return

        offset = self._page_start_offsets[self.current] if (preserve and self.pages and self._page_start_offsets) else 0
        page_chars = self._compute_page_chars()
        self._page_chars = page_chars
        full = self.full_text
        self.pages, self._page_start_offsets = self._paginate(full, page_chars)
        if preserve:
            self.current = self._page_index_for_offset(offset)
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
        # 控制栏宽度跟随屏宽（如日志面板展开/折叠改变了可用宽度）
        self._layout_nav()
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
        local = global_offset - self._page_start_offsets[page_idx]
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

    def _layout_nav(self):
        """按屏幕宽度响应化底部控制栏：把播放键、滑块、音色成组靠左，速度滑块随屏宽
        缩短，并压缩子项间距与两侧箭头图标，确保最右的向后翻页键（CHEVRON_RIGHT）
        完整贴在屏幕最右边、绝不被挤出屏外。在 __init__ / 窗口缩放 / 日志展开时调用。"""
        w = int(self.ft_page.width or 1400)
        if w < 480:            # 手机竖屏：极紧凑，保证向后翻页键完整可见
            # 两侧箭头缩小；播放键靠近向前翻页键；滑块随屏宽；子项间距压到 0
            self.prev_btn.icon_size = 30
            self.next_btn.icon_size = 30
            self.read_btn.icon_size = 30
            self.speed_slider.width = max(60, int(w * 0.20))
            self.voice_dd.width = 66
            self.speed_label.width = 30
            self.nav_row.spacing = 0
        elif w < 800:          # 小平板 / 窄窗
            self.prev_btn.icon_size = 36
            self.next_btn.icon_size = 36
            self.read_btn.icon_size = 36
            self.speed_slider.width = max(90, int(w * 0.22))
            self.voice_dd.width = 84
            self.speed_label.width = 36
            self.nav_row.spacing = 4
        else:                  # 桌面宽窗
            self.prev_btn.icon_size = 40
            self.next_btn.icon_size = 40
            self.read_btn.icon_size = 24
            self.speed_slider.width = 130
            self.voice_dd.width = 110
            self.speed_label.width = 42
            self.nav_row.spacing = 10
        try:
            self.ft_page.update()
        except Exception:
            pass

    def _on_resize(self, e):
        # 窗口变化：重新分页（字号/每页字符数随之调整，并保留进度）
        self._layout_nav()
        self._recompute_layout(preserve=True)

    def _on_speed(self, e):
        """倍速滑块拖动中：实时更新倍速与标签，并防抖地"从当前句用新倍速立即重播"。"""
        v = float(e.control.value)
        self.tts.speed = v
        self.speed_label.value = f"{v:.1f}x"
        self.ft_page.update()
        self._schedule_restart()

    def _on_speed_end(self, e):
        """倍速滑块松手：确保最终按新倍速立即重播（覆盖快速拖动未触发的情况）。"""
        self._schedule_restart()

    def _on_voice(self, e):
        """音色下拉：立即切换音色，并从当前句用新音色重播（若正在朗读）。"""
        self.tts.voice = e.control.value or "male"
        self.ft_page.update()
        if self._is_reading:
            asyncio.create_task(self._restart_from_current_sentence())

    def _schedule_restart(self):
        """防抖：朗读中调速时，停止旧播放、0.3s 后以新倍速从当前句重播。
        拖动过程中定时器不断被重置，仅在你停手后重启一次，避免反复打断。"""
        if not self._is_reading:
            return
        if self._restart_timer is not None:
            self._restart_timer.cancel()
        loop = asyncio.get_event_loop()
        self._restart_timer = loop.call_later(
            0.3, lambda: asyncio.create_task(self._restart_from_current_sentence())
        )

    async def _restart_from_current_sentence(self):
        """停止当前朗读，并以最新速度/音色从"当前句"立即重新朗读。"""
        if not self._is_reading or self._read_task is None:
            return
        start = self._current_sentence_idx if self._current_sentence_idx >= 0 else 0
        # 取消原播放（cancel 比等 stop_event 更可靠，避免旧任务残留）
        await self._cancel_read_task()
        # 以新参数从当前句重启
        self._tts_stop_event.clear()
        self._is_reading = True
        self.read_btn.icon = ft.Icons.STOP_CIRCLE
        self.read_btn.tooltip = "停止朗读"
        self.ft_page.update()
        self._read_task = asyncio.create_task(self._read_all(start_sentence=start))

    # ------------------------------------------------------------------
    # 点击句子选择朗读起点
    # ------------------------------------------------------------------
    def _on_sentence_click(self, idx, e):
        """句子被点击（on_click 为同步回调）：调度"从该句开始朗读"。"""
        asyncio.create_task(self._start_reading_from(idx))

    async def _start_reading_from(self, idx: int):
        """停止当前朗读（若有），并从指定句子开始朗读。"""
        if self._is_reading:
            self._tts_stop_event.set()
        # 不论是否正在朗读，先彻底取消旧任务，避免两个朗读循环重叠
        await self._cancel_read_task()
        # 进入朗读状态，从该句开始
        self._tts_stop_event.clear()
        self._is_reading = True
        self.read_btn.icon = ft.Icons.STOP_CIRCLE
        self.read_btn.tooltip = "停止朗读"
        self.ft_page.update()
        self._read_task = asyncio.create_task(self._read_all(start_sentence=idx))

    async def _cancel_read_task(self, timeout: float = 2.0):
        """彻底取消并等待旧的朗读协程结束，保证任意时刻只有一个朗读任务。

        根因（v1.1.2 修复）：停止→再启动时旧 _read_task 并未被取消，
        它仍在后台用旧 Audio 控件继续播放；新会话 _tts_stop_event.clear()
        又把它"复活"，导致两个 play_sequential 并发、抢同一个 Audio 控件与
        Flet invoke —— 新会话首段 on_loaded 永不触发、play() 超时无声音。
        因此每次启动新朗读前，必须先 cancel 旧任务并等其真正退出。"""
        task = self._read_task
        if task is None or task.done():
            self._read_task = None
            return
        task.cancel()
        try:
            # shield 保护旧任务本身不被外层 wait_for 的超时取消二次打断；
            # 这里只是等它因 CancelledError 正常退出
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            # 旧任务已被取消，或卡在不可中断的 invoke（如 play() 10s 超时），
            # 后者让它自己在后台死，不阻塞新会话启动
            pass
        finally:
            self._read_task = None

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
            if self._restart_timer is not None:
                self._restart_timer.cancel()
                self._restart_timer = None
            # 先彻底取消旧朗读协程，避免停止后仍残留后台任务
            await self._cancel_read_task()
            # 复用收尾逻辑：清高亮 / 停播放 / 复位按钮
            await self._finalize_reading()
            print(f"[BookViewer] 停止朗读")
        else:
            # 开始朗读：先确保没有残留的朗读协程（停止→再启动必须干净），
            # 否则旧任务会被新会话 clear 的 stop_event"复活"而并发抢 Audio。
            await self._cancel_read_task()
            # 优先从已恢复/已点击的句开始（否则当前页第一句）
            start = self._current_sentence_idx if self._current_sentence_idx >= 0 else 0
            self._tts_stop_event.clear()
            self._is_reading = True
            self.read_btn.icon = ft.Icons.STOP_CIRCLE
            self.read_btn.tooltip = "停止朗读"
            self.ft_page.update()
            print(f"[BookViewer] 开始朗读（从第{start + 1}句）")
            self._read_task = asyncio.create_task(self._read_all(start_sentence=start))

    async def _apply_resume_highlight(self):
        """打开书籍后：若存在续读位置，把光标定位到该句并高亮，但不自动朗读。

        按钮保持"播放"状态（用户按下播放键时从该行继续朗读）。
        """
        if self._pending_resume_sentence is not None and self._pending_resume_sentence >= 0:
            start = self._pending_resume_sentence
            self._pending_resume_sentence = None
            self._current_sentence_idx = start
            print(f"[BookViewer] 恢复续读位置：第{self.current + 1}页第{start + 1}句（待播放）")
            await self._highlight_sentence(start)

    async def _wait_for(self, seconds: float, done_task=None):
        """等待 seconds 秒，但随时可被停止事件中断；若 done_task 已完成（整页音频已播完）
        则提前返回，避免估算时长偏长导致的翻页前静音停顿。"""
        step = 0.1
        elapsed = 0.0
        while elapsed < seconds and not self._tts_stop_event.is_set():
            if done_task is not None and done_task.done():
                return
            await asyncio.sleep(step)
            elapsed += step

    async def _read_all(self, start_sentence=0):
        """从当前页的 start_sentence 句开始朗读，自动翻页；逐句记录位置。

        翻页停顿优化：
        - 播放当前页时并行预取下一页音频（synthesize_to_path），翻页后直接播放、
          无需再联网合成，消除翻页后的网络等待。
        - 逐句高亮等待以"真实音频播完"为准（done_task），估算时长偏长时提前结束，
          消除翻页前的静音停顿。
        """
        # ---- 移动端：单 Audio + COMPLETED 事件链顺序播放（v1.0.45）----
        # 按师父架构：页面只创建【一个】Audio 控件，监听 on_state_change 的
        # COMPLETED 事件驱动下一首（play_next）；切歌时改 src + play()、不手动
        # release（ExoPlayer 处理换源）；不用 time.sleep / for 循环硬等。
        # 边播边转（合成一句~1s，与播放并行），零整本预处理延迟。
        # （v1.0.44 的整本 concat 仍保留在 _read_all_mobile_continuous，
        #  若本方案在真机失败可一行切回兜底。）
        if self.tts._is_mobile():
            await self._read_all_mobile_sequential(start_sentence)
            return
        # ---- 桌面端：逐段朗读（pygame 无 player 冲突问题）----
        # 每段都走"创建 Audio + 加载"的可靠路径（真机 100% 出声），因此不再有
        # "首段/后续段"之分；ping-pong 仅用于翻页零等待（不等合成）。
        # 不变量：buf[cur_buf] 永远装着"当前段"的音频——
        #   首段预合成到 buf[0]；后续段由上一段的并行任务合成到 buf[1-cur_buf]。
        tmp_dir = self.tts._mp3_temp_dir()
        buf_paths = [
            os.path.join(tmp_dir, "tmpbookreader1.mp3"),
            os.path.join(tmp_dir, "tmpbookreader2.mp3"),
        ]
        first_page = True
        cur_buf = 0           # 当前段音频所在缓冲下标
        pending = None         # 下一段的并行合成任务

        # 预合成首段（含可能的 resume 起始句）到 buf[0]
        text0 = self.pages[self.current]
        sentences0 = self._split_into_sentences_with_offsets(text0)
        start_idx0 = start_sentence if first_page else 0
        seg0 = text0[sentences0[start_idx0][1]:] if start_idx0 > 0 else text0
        await self.tts.synthesize_to_path_named(seg0, buf_paths[0])

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
                page_char_offset = self._page_start_offsets[self.current]

                start_idx = start_sentence if first_page else 0
                first_page = False

                if start_idx <= 0:
                    speak_text = text
                else:
                    speak_text = text[sentences[start_idx][1]:]

                durations = [estimate_duration(s) for s, _ in sentences]

                # 当前段音频在 buf[cur_buf]（首段预合成 / 上一段并行合成好）
                mp3 = buf_paths[cur_buf]
                if not os.path.exists(mp3):
                    # 预取失败兜底：现场合成到当前缓冲
                    mp3 = await self.tts.synthesize_to_path_named(speak_text, buf_paths[cur_buf])
                    if mp3 is None:
                        await self._wait(sum(durations) if durations else 0.0, self._tts_stop_event)
                        if self._tts_stop_event.is_set():
                            break
                        if self.current < len(self.pages) - 1:
                            self.current += 1
                            self._update_page_display()
                        else:
                            break
                        continue

                # 并行合成"下一段"到另一缓冲（翻页零等待；通常播放期间已完成）
                other = 1 - cur_buf
                nxt = self.current + 1
                if nxt < len(self.pages):
                    pending = asyncio.create_task(
                        self.tts.synthesize_to_path_named(self.pages[nxt], buf_paths[other])
                    )
                else:
                    pending = None

                # 完整播放当前段 mp3（每段新建独立 Audio，可靠出声）
                speak_task = asyncio.create_task(
                    self._speak_text_from_file(speak_text, mp3)
                )

                # 逐句高亮 + 记录位置，与朗读节奏同步；整页播完则提前结束等待
                for i in range(start_idx, len(sentences)):
                    if self._tts_stop_event.is_set():
                        break
                    await self._highlight_sentence(i)
                    # 朗读到该句即记录"绝对字符偏移"，作为续读位置
                    global_off = page_char_offset + sentences[i][1]
                    self._save_position(global_off)
                    await self._wait_for(durations[i], speak_task)

                # 等待整页朗读结束
                try:
                    await speak_task
                except Exception as ex:
                    print(f"[BookViewer] 朗读任务异常: {ex}")

                # 等待下一段并行合成完成（通常已完成）
                if pending is not None:
                    try:
                        res = await pending
                        if res is None:
                            print("[BookViewer] 下一段合成失败")
                    except Exception as ex:
                        print(f"[BookViewer] 并行合成异常: {ex}")
                    pending = None

                if self._tts_stop_event.is_set():
                    break

                # 删除"已播放"的当前缓冲，并切换到下一段已合成好的另一缓冲
                try:
                    if os.path.exists(buf_paths[cur_buf]):
                        os.unlink(buf_paths[cur_buf])
                        print(f"[BookViewer] 已删除旧缓冲 tmpbookreader{cur_buf + 1}.mp3")
                except Exception:
                    pass
                cur_buf = 1 - cur_buf

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

        # 清理：取消未完成的并行合成 + 删除 ping-pong 双缓冲文件
        if pending is not None:
            if not pending.done():
                pending.cancel()
            else:
                try:
                    p = pending.result()
                    if p and os.path.exists(p):
                        os.unlink(p)
                except Exception:
                    pass
        for bp in buf_paths:
            try:
                if os.path.exists(bp):
                    os.unlink(bp)
            except Exception:
                pass

        # 朗读结束，恢复按钮状态
        self._is_reading = False
        self._tts_stop_event.clear()
        if self._restart_timer is not None:
            self._restart_timer.cancel()
            self._restart_timer = None
        self._read_task = None
        self.read_btn.icon = ft.Icons.PLAY_ARROW
        self.read_btn.tooltip = "朗读全书（点击句子可从该句开始）"
        await self._clear_highlight()
        self.ft_page.update()
        print(f"[BookViewer] 朗读结束")

        # 结束时再保存一次当前位置（兜底；读句中已逐句保存）
        self._save_position()

    # ==================================================================
    # 移动端单 Audio + COMPLETED 事件链顺序朗读（v1.0.45）
    # ==================================================================
    async def _read_all_mobile_sequential(self, start_sentence=0):
        """移动端单 Audio + COMPLETED 事件链顺序朗读（v1.0.45，按师父架构）。

        页面只创建一个 flet_audio.Audio 控件；play_sequential 监听
        on_state_change 的 COMPLETED 事件驱动下一句（play_next），
        切句时改 src + play()、不手动 release（ExoPlayer 处理换源）；
        不用 time.sleep / for 循环硬等。

        句子高亮由 play_sequential 的 on_seg_start 回调（每段开始播放时
        触发）事件驱动：保存位置 + 自动翻页 + 高亮当前句。彻底
        绕开 v1.0.36~v1.0.43 所有"复用重载 / 第二个 player"坑——
        因为本方案【不 release】，ExoPlayer 自行处理换源，等于每段都走
        "首段创建"的可靠路径（首段 100% 出声已被反复验证）。"""
        # 1) 收集剩余句子（文本 + 绝对字符偏移），跨页拼成扁平列表
        all_sent = []  # [(text, abs_offset), ...]
        first_page = True
        for pi in range(self.current, len(self.pages)):
            text = self.pages[pi]
            if not text.strip():
                continue
            sents = self._split_into_sentences_with_offsets(text)
            if not sents:
                continue
            sidx = start_sentence if first_page else 0
            base = self._page_start_offsets[pi]
            for j in range(sidx, len(sents)):
                s_text = sents[j][0]
                if not s_text.strip():
                    continue
                all_sent.append((s_text, base + sents[j][1]))
            first_page = False

        if not all_sent:
            print("[BookViewer] 无可读句子，停止顺序朗读")
            await self._finalize_reading()
            return

        texts = [s for s, _ in all_sent]
        offsets = [o for _, o in all_sent]
        print(f"[BookViewer] 顺序朗读：共 {len(texts)} 句"
              f"（单 Audio + COMPLETED 事件链，边播边转）")

        # 2) on_seg_start 回调：每段开始播放时由 play_sequential 触发
        #    （事件驱动，不用硬等）——保存位置 + 自动翻页 + 高亮当前句
        def on_seg_start(idx, text):
            if idx >= len(offsets):
                return
            off = offsets[idx]
            self._save_position(off)
            self._ensure_page_for_offset(off)
            try:
                si = self._sentence_index_at_offset(self.current, off)
                loop = asyncio.get_event_loop()
                loop.create_task(self._highlight_sentence(si))
            except Exception as ex:
                print(f"[BookViewer] 高亮调度异常: {ex}")

        # 3) 单 Audio 顺序播放（事件驱动，边播边转；桌面端走 pygame）
        await self.tts.play_sequential(
            texts, self._tts_stop_event, on_seg_start=on_seg_start
        )
        await self._finalize_reading()
        print("[BookViewer] 顺序朗读结束")

    # ==================================================================
    # 移动端整本连续朗读（v1.0.44）：单个 player 播完整场
    # （v1.0.45 起作为顺序朗读失败时的兜底，未默认启用）
    # ==================================================================
    def _ensure_page_for_offset(self, global_offset: int):
        """若 global_offset 不在当前页，翻到对应页（连续朗读用）。"""
        target = self.current
        for pi in range(len(self.pages)):
            nxt = self._page_start_offsets[pi + 1] \
                if pi + 1 < len(self.pages) else 10 ** 18
            if self._page_start_offsets[pi] <= global_offset < nxt:
                target = pi
                break
        if target != self.current:
            self.current = target
            self._update_page_display()  # 渲染新页（重置 _page_sentences / 清高亮）
            print(f"[BookViewer] 连续朗读自动翻到第{self.current + 1}页")

    async def _read_all_mobile_continuous(self, start_sentence=0):
        """移动端整本连续朗读（v1.0.44）：

        把从 start_sentence 句到书末的所有句子拼成一个 mp3，用【单个】AudioPlayer
        一次性播完（首段可靠路径，100% 出声）。句子高亮用估算时长计时驱动，
        与音频进度解耦（不依赖 on_loaded 之外的音频事件），并随阅读进度自动翻页。

        这彻底绕开 flet_audio 在安卓上"第二个 player 与原生残留资源冲突 →
        on_loaded 永不触发 → 静音"的坑——因为全程只有一个 player（首个）。
        """
        # 1) 收集剩余句子（文本 + 绝对字符偏移）
        all_sent = []  # [(text, abs_offset), ...]
        first_page = True
        for pi in range(self.current, len(self.pages)):
            text = self.pages[pi]
            if not text.strip():
                continue
            sents = self._split_into_sentences_with_offsets(text)
            if not sents:
                continue
            sidx = start_sentence if first_page else 0
            base = self._page_start_offsets[pi]
            for j in range(sidx, len(sents)):
                s_text = sents[j][0]
                if not s_text.strip():
                    continue
                all_sent.append((s_text, base + sents[j][1]))
            first_page = False

        if not all_sent:
            print("[BookViewer] 无可读句子，停止连续朗读")
            await self._finalize_reading()
            return

        # 2) 拼成单个 mp3（流式写入，避免整本字节驻留内存）
        tmp_dir = self.tts._mp3_temp_dir()
        full_path = os.path.join(tmp_dir, "tmpbookreader_full.mp3")
        print(f"[BookViewer] 连续朗读：合成 {len(all_sent)} 句为一个 mp3 ...")
        mp3 = await self.tts.synthesize_concat([s for s, _ in all_sent], full_path)
        total_dur = sum(estimate_duration(s) for s, _ in all_sent)

        # 3) 启动"单个 player 播完整 mp3"（桌面端回退 pygame）
        play_task = None
        if mp3 is not None:
            play_task = asyncio.create_task(
                self.tts.play_continuous_mp3(mp3, total_dur, self._tts_stop_event)
            )
        else:
            print("[BookViewer] 连续朗读合成失败，回退纯高亮（无声）")

        # 4) 高亮循环：按估算时长逐句高亮 + 记录位置 + 自动翻页；
        #    play_task 完成（整本播完）即提前结束等待
        i = 0
        while i < len(all_sent) and self._is_reading and not self._tts_stop_event.is_set():
            s_text, off = all_sent[i]
            self._save_position(off)
            self._ensure_page_for_offset(off)
            idx = self._sentence_index_at_offset(self.current, off)
            await self._highlight_sentence(idx)
            await self._wait_for(estimate_duration(s_text), play_task)
            i += 1

        # 5) 等待播放真正结束（用户中途停止时 play_task 已因 stop_event 退出）
        if play_task is not None:
            try:
                await play_task
            except Exception as ex:
                print(f"[BookViewer] 连续朗读播放异常: {ex}")

        # 6) 清理
        try:
            if mp3 and os.path.exists(full_path):
                os.unlink(full_path)
        except Exception:
            pass
        await self._finalize_reading()
        print("[BookViewer] 连续朗读结束")

    async def _finalize_reading(self):
        """朗读收尾：恢复按钮状态、清高亮、清理计时器、停止播放。"""
        self._is_reading = False
        self._tts_stop_event.clear()
        if self._restart_timer is not None:
            self._restart_timer.cancel()
            self._restart_timer = None
        self._read_task = None
        self.read_btn.icon = ft.Icons.PLAY_ARROW
        self.read_btn.tooltip = "朗读全书（点击句子可从该句开始）"
        # 结束后停止 flet_audio（释放 player）
        try:
            self.tts.stop()
        except Exception:
            pass
        await self._clear_highlight()
        self.ft_page.update()
        self._save_position()

    async def _speak_text(self, text: str, prefetched_path=None):
        """使用跨平台 TTS 朗读文本（支持停止）。prefetched_path 为预取好的 mp3 文件。"""
        if not text.strip():
            return

        print(f"[BookViewer] TTS朗读: {len(text)} 字符")
        try:
            await self.tts.speak(text, self._tts_stop_event, prefetched_path=prefetched_path)
        except Exception as ex:
            print(f"[BookViewer] TTS错误: {ex}")
            import traceback
            traceback.print_exc()

    async def _speak_text_from_file(self, text: str, mp3_path):
        """用跨平台 TTS 播放已合成好的 mp3 文件（每段都走"新建 Audio"的可靠路径）。"""
        if not text.strip():
            return

        print(f"[BookViewer] TTS朗读(段): {len(text)} 字符")
        try:
            await self.tts.speak_file(mp3_path, self._tts_stop_event)
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
                    # 变长分页下用真实页起始偏移（page_chars 仅为名义估算）
                    global_offset = self._page_start_offsets[self.current] if self._page_start_offsets else self.current * self._page_chars
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

            page_idx = self._page_index_for_offset(global_offset)
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
