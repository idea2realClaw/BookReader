import flet as ft
import asyncio

from reader import open_book, BookReader


class BookViewer(ft.Container):
    """Single-page book viewer with TTS read-aloud support."""

    def __init__(self, reader: BookReader, page: ft.Page, on_close=None):
        super().__init__(expand=True)
        self.reader = reader
        self.ft_page = page
        self.on_close = on_close
        self.current = 0
        self._is_reading = False
        self._stop_reading = False

        self.page_text = ft.Text(
            selectable=True,
            size=18,
            color=ft.Colors.BLACK87,
            no_wrap=False,
            font_family="sans-serif",
        )

        self._update_font_size()
        self.page_label = ft.Text(size=12, color=ft.Colors.BLACK54)

        # 朗读按钮
        self.read_btn = ft.IconButton(
            ft.Icons.PLAY_ARROW,
            tooltip="朗读当前页",
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

    async def _toggle_read(self, e):
        """切换朗读状态"""
        if self._is_reading:
            # 停止朗读
            self._stop_reading = True
            self._is_reading = False
            self.read_btn.icon = ft.Icons.PLAY_ARROW
            self.read_btn.tooltip = "朗读当前页"
            self.ft_page.update()
            print(f"[BookViewer] 停止朗读")
        else:
            # 开始朗读
            self._is_reading = True
            self._stop_reading = False
            self.read_btn.icon = ft.Icons.STOP_CIRCLE
            self.read_btn.tooltip = "停止朗读"
            self.ft_page.update()
            print(f"[BookViewer] 开始朗读")
            
            # 在后台任务中朗读
            asyncio.create_task(self._read_current_page())

    async def _read_current_page(self):
        """朗读当前页，然后自动翻页"""
        while self._is_reading and not self._stop_reading:
            try:
                # 获取当前页文本
                text = self.reader.get_page(self.current)
                
                if not text:
                    print(f"[BookViewer] 第{self.current+1}页无文本，停止朗读")
                    break
                
                print(f"[BookViewer] 朗读第{self.current+1}页，文本长度: {len(text)} 字符")
                
                # 调用TTS朗读（使用系统TTS或在线TTS）
                await self._speak_text(text)
                
                # 检查是否需要停止
                if self._stop_reading or not self._is_reading:
                    print(f"[BookViewer] 朗读被停止")
                    break
                
                # 自动翻页
                if self.current < self.reader.get_page_count() - 1:
                    self.current += 1
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
        self._stop_reading = False
        self.read_btn.icon = ft.Icons.PLAY_ARROW
        self.read_btn.tooltip = "朗读当前页"
        self.ft_page.update()
        print(f"[BookViewer] 朗读结束")

    async def _speak_text(self, text: str):
        """使用TTS朗读文本（简化版：使用Windows系统TTS）"""
        print(f"[BookViewer] TTS朗读: {len(text)} 字符")
        
        if self.ft_page.web:
            # 浏览器模式：使用Web Speech API
            print(f"[BookViewer] 浏览器模式暂不支持TTS，跳过")
            # 等待一段时间模拟朗读
            words = len(text) / 3  # 中文约每秒3字
            await asyncio.sleep(min(words / 10, 5))  # 最多等待5秒
        else:
            # 桌面模式：使用Windows系统TTS（SAPI）
            try:
                import subprocess
                import tempfile
                import os
                
                # 截断文本（避免过长）
                text = text[:2000]
                
                # 创建VBScript临时文件（调用Windows SAPI）
                vbs_script = f'''Set speak = CreateObject("SAPI.SpVoice")
speak.Rate = 2
speak.Speak "{text.replace(chr(34), "'").replace(chr(10), " ").replace(chr(13), " ")}"
'''
                
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.vbs', encoding='ansi') as f:
                    f.write(vbs_script)
                    vbs_path = f.name
                
                print(f"[BookViewer] 运行Windows TTS: {vbs_path}")
                
                # 运行VBScript（同步等待完成）
                result = subprocess.run(['cscript', '//nologo', vbs_path], 
                                    capture_output=True, 
                                    text=True,
                                    timeout=300)  # 5分钟超时
                
                print(f"[BookViewer] TTS完成: {result.returncode}")
                
                # 清理临时文件
                try:
                    os.unlink(vbs_path)
                except:
                    pass
                
            except subprocess.TimeoutExpired:
                print(f"[BookViewer] TTS超时")
            except Exception as ex:
                print(f"[BookViewer] TTS错误: {ex}")
                # 至少等待一段时间
                await asyncio.sleep(2)
