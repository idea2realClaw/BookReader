"""
实时日志窗口组件
捕获 stdout/stderr 并在 UI 中实时显示
"""
import sys
import io
import threading
from collections import deque
import datetime
import flet as ft

class LogCapture(io.StringIO):
    """捕获 stdout/stderr 并转发到 UI"""
    
    def __init__(self, max_lines=1000):
        super().__init__()
        self.max_lines = max_lines
        self.lines = deque(maxlen=max_lines)
        self.lock = threading.Lock()
        self._listeners = []
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._buffer = ""
        # 同时写入日志文件，方便调试
        self._log_file = open("bookreader_debug.log", "a", encoding="utf-8")
        self._log_file.write(f"\n\n{'='*50}\n")
        self._log_file.write(f"BookReader 启动于 {datetime.datetime.now()}\n")
        self._log_file.write(f"{'='*50}\n\n")
        self._log_file.flush()
    
    def write(self, text):
        """捕获输出并存储"""
        # 同时输出到原始 stdout（这样终端也能看到）
        try:
            self._original_stdout.write(text)
        except:
            pass
        
        # 写入调试文件
        try:
            self._log_file.write(text)
            self._log_file.flush()
        except:
            pass
        
        # 缓冲直到完整一行
        self._buffer += text
        if '\n' in self._buffer:
            lines = self._buffer.split('\n')
            # 最后一行可能不完整，保留到下次
            self._buffer = lines[-1]
            
            # 处理完整的行
            for line in lines[:-1]:
                if line:  # 忽略空行
                    with self.lock:
                        # 添加时间戳
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                        formatted_line = f"[{timestamp}] {line}"
                        self.lines.append(formatted_line)
                        
                        # 通知所有监听器
                        for callback in self._listeners:
                            try:
                                callback(formatted_line)
                            except:
                                pass
    
    def flush(self):
        """刷新缓冲区"""
        try:
            self._original_stdout.flush()
        except:
            pass
        
        # 输出剩余的缓冲区内容
        if self._buffer:
            line = self._buffer
            self._buffer = ""
            if line:
                with self.lock:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    formatted_line = f"[{timestamp}] {line}"
                    self.lines.append(formatted_line)
                    
                    for callback in self._listeners:
                        try:
                            callback(formatted_line)
                        except:
                            pass
    
    def add_listener(self, callback):
        """添加日志监听器"""
        self._listeners.append(callback)
    
    def remove_listener(self, callback):
        """移除日志监听器"""
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def get_lines(self):
        """获取所有日志行"""
        with self.lock:
            return list(self.lines)


class LogWindow(ft.Container):
    """可折叠的日志窗口组件"""
    
    def __init__(self, page: ft.Page, max_height=200):
        super().__init__()
        self.ft_page = page
        self.max_height = max_height
        self.is_collapsed = False
        self.log_capture = None
        
        # 日志显示区域（使用 TextField 支持多行选择）
        self.log_text = ft.TextField(
            value="",
            read_only=True,
            multiline=True,
            expand=True,
            min_lines=5,
            max_lines=15,
            text_size=11,
            text_style=ft.TextStyle(
                font_family="Consolas",
            ),
            color=ft.Colors.BLACK87,
            bgcolor=ft.Colors.GREY_50,
            border_color=ft.Colors.GREY_300,
            focused_border_color=ft.Colors.BLUE,
            cursor_color=ft.Colors.BLACK87,
            content_padding=5,
        )
        
        # 折叠/展开按钮
        self.toggle_btn = ft.IconButton(
            ft.Icons.EXPAND_MORE,
            tooltip="折叠日志窗口",
            icon_size=20,
            on_click=self._toggle_collapse,
        )
        
        # 清除按钮
        self.clear_btn = ft.IconButton(
            ft.Icons.CLEAR,
            tooltip="清除日志",
            icon_size=20,
            on_click=self._clear_logs,
        )
        
        # 标题栏
        self.header = ft.Row(
            [
                ft.Text("实时日志", size=14, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [self.clear_btn, self.toggle_btn],
                    spacing=0,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        
        # 日志容器
        self.log_container = ft.Container(
            content=self.log_text,
            expand=True,
            padding=0,
        )
        
        # 主容器
        self.content = ft.Column(
            [
                self.header,
                self.log_container,
            ],
            spacing=5,
            expand=True,
        )
        
        self.expand = False
        self.height = max_height
        self.padding = 10
        self.bgcolor = ft.Colors.WHITE
        self.border = ft.Border(
            left=ft.BorderSide(1, ft.Colors.GREY_300),
            top=ft.BorderSide(2, ft.Colors.BLUE),
            right=ft.BorderSide(1, ft.Colors.GREY_300),
            bottom=ft.BorderSide(1, ft.Colors.GREY_300),
        )
    
    def _toggle_collapse(self, e):
        """切换折叠状态"""
        self.is_collapsed = not self.is_collapsed
        
        if self.is_collapsed:
            # 折叠
            self.log_container.visible = False
            self.height = 40
            self.toggle_btn.icon = ft.Icons.EXPAND_MORE
            self.toggle_btn.tooltip = "展开日志窗口"
        else:
            # 展开
            self.log_container.visible = True
            self.height = self.max_height
            self.toggle_btn.icon = ft.Icons.EXPAND_LESS
            self.toggle_btn.tooltip = "折叠日志窗口"
        
        self.ft_page.update()
    
    def _clear_logs(self, e):
        """清除所有日志"""
        self.log_text.value = ""
        self.ft_page.update()
    
    def setup_log_capture(self):
        """设置日志捕获"""
        self.log_capture = LogCapture()
        
        # 添加监听器
        self.log_capture.add_listener(self._on_new_log)
        
        # 重定向 stdout 和 stderr
        sys.stdout = self.log_capture
        sys.stderr = self.log_capture
        
        print("=" * 50)
        print("日志窗口已启动")
        print("=" * 50)
    
    def _on_new_log(self, line: str):
        """新日志到达时的回调"""
        # 在 UI 线程中添加日志行
        def add_line():
            try:
                # 追加日志到 TextField
                if self.log_text.value:
                    self.log_text.value += "\n" + line
                else:
                    self.log_text.value = line
                
                # 限制显示的行数
                max_display = 500
                lines = self.log_text.value.split("\n")
                if len(lines) > max_display:
                    self.log_text.value = "\n".join(lines[-max_display:])
                
                # 滚动到底部（设置光标位置到末尾）
                self.log_text.value += ""  # 触发更新
                self.ft_page.update()
            except Exception as e:
                pass
        
        # 使用页面的异步更新机制
        try:
            self.ft_page.add_async_callback(add_line)
        except:
            # 如果失败，直接调用
            add_line()
    
    def cleanup(self):
        """清理资源，恢复 stdout/stderr"""
        if self.log_capture:
            # 恢复标准输出
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
