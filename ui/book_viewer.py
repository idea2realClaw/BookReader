import flet as ft
import math
import threading
import time

from reader import open_book, BookReader


class BookViewer(ft.Container):
    """Single-page book viewer with a simulated 3D page-turn animation."""

    def __init__(self, reader: BookReader, page: ft.Page, on_close=None):
        super().__init__(expand=True)
        self.reader = reader
        self.ft_page = page
        self.on_close = on_close
        self.current = 0

        self._width = page.width or 360
        self._height = page.height or 640

        # The page that is revealed underneath during the flip.
        self.back_container = ft.Container(
            width=self._width,
            height=self._height,
            bgcolor=ft.Colors.WHITE,
            padding=20,
            alignment=ft.Alignment.TOP_LEFT,
        )

        # The animating page that flips away.
        self.flip_container = ft.Container(
            width=self._width,
            height=self._height,
            bgcolor=ft.Colors.WHITE,
            padding=20,
            alignment=ft.Alignment.TOP_LEFT,
        )

        self._flip_alignment = ft.Alignment.CENTER_LEFT

        # Shadow overlay on the revealed page (grows with the flip).
        self.shadow_overlay = ft.Container(
            width=self._width,
            height=self._height,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_RIGHT,
                end=ft.Alignment.CENTER_LEFT,
                colors=["#00000000", "#00000000"],
            ),
        )

        self.page_text = ft.Text(
            selectable=True,
            size=18,
            color=ft.Colors.BLACK87,
            no_wrap=False,
        )
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

        self.body = ft.Stack(
            [
                self.back_container,
                self.shadow_overlay,
                self.flip_container,
                # Tap zones for turning pages.
                ft.GestureDetector(
                    content=ft.Container(width=self._width, height=self._height),
                    on_tap=self._on_tap,
                ),
            ],
            expand=True,
        )

        self.content = ft.Column(
            [
                self.header,
                ft.Container(
                    content=self.body,
                    expand=True,
                    border=ft.Border.all(1, ft.Colors.BLACK12),
                    border_radius=8,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ),
                ft.Container(
                    content=self.page_label,
                    alignment=ft.Alignment.CENTER,
                    padding=4,
                ),
            ],
            spacing=0,
            expand=True,
        )

        self._animating = False
        self._update_page_display(animate=False)
        self.ft_page.on_resize = self._on_resize

    def _on_resize(self, e):
        self._width = max(self.ft_page.width or 360, 200)
        self._height = max(self.ft_page.height or 640, 300)
        self.back_container.width = self._width
        self.back_container.height = self._height
        self.flip_container.width = self._width
        self.flip_container.height = self._height
        self.shadow_overlay.width = self._width
        self.shadow_overlay.height = self._height
        self.body.controls[3].content.width = self._width
        self.body.controls[3].content.height = self._height
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

    def _on_tap(self, e: ft.TapEvent):
        if self._animating:
            return
        x = getattr(e, "local_x", self._width / 2)
        if x < self._width * 0.4:
            self.prev_page()
        else:
            self.next_page()

    def _build_page_content(self, text: str):
        return ft.Column(
            [
                ft.Text(
                    text,
                    size=18,
                    color=ft.Colors.BLACK87,
                    selectable=True,
                    no_wrap=False,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _update_page_display(self, animate=True):
        text = self.reader.get_page(self.current)
        self.page_text.value = text
        self.page_label.value = f"第 {self.current + 1} / {self.reader.get_page_count()} 页"

        page_view = self._build_page_content(text)
        self.flip_container.content = page_view
        self.back_container.content = self._build_page_content(text)
        self._reset_transforms()
        self.ft_page.update()

    def _reset_transforms(self):
        m = ft.Matrix4.identity()
        self.flip_container.transform = ft.Transform(matrix=m, alignment=self._flip_alignment)
        self.shadow_overlay.gradient = ft.LinearGradient(
            begin=ft.Alignment.CENTER_RIGHT,
            end=ft.Alignment.CENTER_LEFT,
            colors=["#00000000", "#00000000"],
        )

    def _perspective_matrix(self, angle: float) -> ft.Matrix4:
        m = ft.Matrix4.identity()
        m.set_entry(3, 2, -0.001)  # perspective
        m.rotate_y(angle)
        return m

    def _apply_frame(self, angle: float, direction: int):
        m = self._perspective_matrix(angle)
        self.flip_container.transform = ft.Transform(matrix=m, alignment=self._flip_alignment)
        alpha = int(60 * abs(math.sin(angle)))
        if direction == 1:
            colors = [f"#000000{alpha:02x}", "#00000000"]
        else:
            colors = ["#00000000", f"#000000{alpha:02x}"]
        self.shadow_overlay.gradient = ft.LinearGradient(
            begin=ft.Alignment.CENTER_RIGHT,
            end=ft.Alignment.CENTER_LEFT,
            colors=colors,
        )
        self.ft_page.update()

    def _animate_flip(self, target: int, direction: int):
        """direction: 1 = next (flip left), -1 = prev (flip right)."""
        self._animating = True
        total = self.reader.get_page_count()
        if not (0 <= target < total):
            self._animating = False
            return

        def prepare():
            back_text = self.reader.get_page(target)
            self.back_container.content = self._build_page_content(back_text)
            front_text = self.reader.get_page(self.current)
            self.flip_container.content = self._build_page_content(front_text)
            self._flip_alignment = (
                ft.Alignment.CENTER_LEFT if direction == 1 else ft.Alignment.CENTER_RIGHT
            )
            self._reset_transforms()
            self.ft_page.update()

        self.ft_page.run(prepare)

        start = 0.0
        end = -math.pi if direction == 1 else math.pi
        steps = 20
        duration = 0.4

        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)
            angle = start + (end - start) * t
            self.ft_page.run(self._apply_frame, angle, direction)
            time.sleep(duration / steps)

        self.current = target

        def finish():
            self._update_page_display(animate=False)
            self._animating = False

        self.ft_page.run(finish)

    def next_page(self):
        if self.current < self.reader.get_page_count() - 1:
            threading.Thread(
                target=self._animate_flip,
                args=(self.current + 1, 1),
                daemon=True,
            ).start()

    def prev_page(self):
        if self.current > 0:
            threading.Thread(
                target=self._animate_flip,
                args=(self.current - 1, -1),
                daemon=True,
            ).start()
