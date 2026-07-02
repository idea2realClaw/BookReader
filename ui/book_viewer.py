import flet as ft


from reader import open_book, BookReader


class BookViewer(ft.Container):
    """Single-page book viewer (simplified, no animation)."""

    def __init__(self, reader: BookReader, page: ft.Page, on_close=None):
        super().__init__(expand=True)
        self.reader = reader
        self.ft_page = page
        self.on_close = on_close
        self.current = 0

        self.page_text = ft.Text(
            selectable=True,
            size=18,
            color=ft.Colors.BLACK87,
            no_wrap=False,
            # 让文字可以自动换行
            font_family="sans-serif",
        )

        # 设置初始字体大小
        self._update_font_size()
        self.page_label = ft.Text(size=12, color=ft.Colors.BLACK54)

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
                    content=ft.Column(
                        [self.page_text],
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                    expand=True,
                    padding=ft.Padding(left=80, top=30, right=80, bottom=30),
                ),
                ft.Row(
                    [
                        ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=self.prev_page, icon_size=40),
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

        self._update_page_display()
        self.ft_page.on_resize = self._on_resize

    def _update_font_size(self):
        """根据页面宽度调整字体大小"""
        width = self.ft_page.width or 1400
        if width > 1400:
            self.page_text.size = 28
        elif width > 1200:
            self.page_text.size = 24
        elif width > 900:
            self.page_text.size = 20
        else:
            self.page_text.size = 18

    def _on_resize(self, e):
        self._update_font_size()
        self.ft_page.update()

    async def _close(self, e):
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

    def _update_page_display(self):
        text = self.reader.get_page(self.current)
        self.page_text.value = text
        self.page_label.value = f"第 {self.current + 1} / {self.reader.get_page_count()} 页"
        # 调试：打印宽度信息
        print(f"[BookViewer] Page width: {self.ft_page.width}, Window width: {self.ft_page.window_width}")
        self.ft_page.update()

    async def next_page(self, e):
        if self.current < self.reader.get_page_count() - 1:
            self.current += 1
            self._update_page_display()

    async def prev_page(self, e):
        if self.current > 0:
            self.current -= 1
            self._update_page_display()
