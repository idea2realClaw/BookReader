"""
主窗口布局：管理内容区域和日志窗口
"""
import flet as ft
import time
from version import APP_VERSION
from ui.bookshelf import BookShelf
from ui.log_window import LogWindow


class MainWindow(ft.Stack):
    """主窗口：内容区(书架/阅读器)铺满固定高度，日志窗口浮于底部并向上展开。

    布局要点（解决"日志盖住翻页键 / 书架被压缩"的问题）：
    - 内容区(书架或阅读器)用 top/left/right/bottom=0 铺满整个 Stack，高度固定 = 屏幕可用高度。
    - 日志窗口设 left/right=0、bottom=0 浮在内容之上（flet 0.85.3 直接给子控件设这些属性定位）：
        * 折叠时只显示 40px 标题栏，书架完整可见(= 屏幕高度 - 50px)；
        * 展开时高度变 200px 且 bottom 锚定不动，故"向上展开、底部不动"。
    - 阅读器通过 set_log_gap() 把翻页栏抬到日志上方，文本区不会过长也不被遮挡。
    """
    
    def __init__(self, page: ft.Page):
        super().__init__(expand=True)
        
        self.ft_page = page
        self.active_viewer = None
        self.log_height = 40  # 日志折叠态默认高度
        
        # 日志窗口（浮于底部，向上展开；默认折叠）
        self.log_window = LogWindow(page, max_height=200)
        self.log_window.on_toggle = self._on_log_toggle
        
        # 创建书架（主内容）
        self.bookshelf = BookShelf(self)

        # 内容容器：铺满整个 Stack（书架/阅读器都在这里切换）。
        # flet 0.85.3 没有 Positioned 包装类，直接给 Stack 子控件设
        # top/left/right/bottom 即可定位（来自 LayoutControl）。
        self.content_container = ft.Container(content=self.bookshelf)
        self.content_container.top = 0
        self.content_container.left = 0
        self.content_container.right = 0
        self.content_container.bottom = 0

        # 日志窗口：左/右贴边、bottom 锚定在 Stack 底部；不设 top，
        # 高度由其自身 height(40/200) 决定，展开时"向上生长、底部不动"。
        self.log_window.left = 0
        self.log_window.right = 0
        self.log_window.bottom = 0

        # 主布局：内容铺底，日志浮顶（Stack 中靠后的控件渲染在上层）
        self.controls = [
            self.content_container,
            self.log_window,
        ]
        
        # 设置日志捕获
        self.log_window.setup_log_capture()
        # 同步初始日志高度（默认折叠 40px）；此处仅记录高度，不触发 update
        # （MainWindow 尚未挂到 page，update 在 __init__ 阶段不安全）
        self.log_height = self.log_window.height
        
        print("[MainWindow] 主窗口已初始化")
    
    def navigate_to_viewer(self, viewer):
        """导航到书籍阅读器"""
        print(f"[MainWindow] 导航到阅读器")
        self.content_container.content = viewer
        self.active_viewer = viewer
        # 让阅读器的翻页栏抬到当前日志高度之上
        if hasattr(viewer, "set_log_gap"):
            viewer.set_log_gap(self.log_height)
        self.ft_page.update()
    
    def navigate_to_shelf(self):
        """导航回书架"""
        print(f"[MainWindow] 导航回书架")
        self.content_container.content = self.bookshelf
        self.active_viewer = None
        self.ft_page.update()
    
    def _on_log_toggle(self, height):
        """日志展开/折叠时：记录高度，并让正在阅读的阅读器把翻页栏抬到日志上方。"""
        self.log_height = height
        if self.active_viewer and hasattr(self.active_viewer, "set_log_gap"):
            self.active_viewer.set_log_gap(height)
        self.ft_page.update()
    
    def cleanup(self):
        """清理资源"""
        self.log_window.cleanup()


VERSION = APP_VERSION  # 版本号（由 version.py 提供，构建时由 release 版本注入）

def main(page: ft.Page):
    """主应用入口"""
    page.title = f"BookReader v{VERSION}"  # 添加版本号到标题
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    
    # 根据视图模式设置窗口大小
    if page.web:
        # 浏览器模式：使用全屏或较大尺寸
        page.window_width = 1200
        page.window_height = 800
    else:
        # 桌面模式：使用全屏尺寸
        page.window_width = 1400
        page.window_height = 900
        page.window_resizable = True
    
    # 创建主窗口
    main_window = MainWindow(page)

    # 上下各留 50px 边距（满足"缩短整体高度、避让状态栏"的需求）。
    # 注意：之前用 SafeArea(minimum_padding=...) 会吃掉底部可用高度且
    # 在 flet 0.85.3 下不向子控件传递紧约束高度，导致底部日志窗 / 翻页键 /
    # TTS 键被裁出屏幕。改用 page.padding：page.add 一定会给直接子控件
    # 一个"撑满剩余区域"的紧约束，内容精确适配、永不裁切。
    page.padding = ft.Padding(top=50, right=0, bottom=50, left=0)

    page.add(main_window)

    # 保存引用以便清理
    page.main_window = main_window
    
    print("[main] 应用已启动")
    print(f"[main] 缓存版本: {int(time.time())}")


if __name__ == "__main__":
    import sys
    import os
    import argparse
    
    # 生成启动时间戳（用于强制浏览器重新加载）
    STARTUP_TIMESTAMP = int(time.time())
    print(f"启动时间戳: {STARTUP_TIMESTAMP}")
    
    # 命令行参数解析
    parser = argparse.ArgumentParser(description="BookReader - 跨平台电子书阅读器")
    parser.add_argument(
        "--mode",
        choices=["desktop", "browser"],
        default="desktop",
        help="运行模式: desktop (桌面/移动原生应用) 或 browser (浏览器模式)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="浏览器模式的主机地址 (默认: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        default=8550,
        type=int,
        help="浏览器模式的端口 (默认: 8550)"
    )
    
    args = parser.parse_args()
    
    print(f"Python version: {sys.version}")
    print(f"Flet version: {ft.__version__}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Running in {args.mode} mode...")
    
    if args.mode == "browser":
        print(f"App will open in browser at: http://{args.host}:{args.port}")
        print(f"禁用缓存: 是 (时间戳: {STARTUP_TIMESTAMP})")
        
        # 添加无缓存参数到 URL
        import webbrowser
        url = f"http://{args.host}:{args.port}?_t={STARTUP_TIMESTAMP}"
        print(f"访问 URL: {url}")
        
        ft.app(
            main,
            assets_dir="assets",
            host=args.host,
            port=args.port,
            view=ft.AppView.WEB_BROWSER
        )
    else:
        # desktop 模式，以及 Android/iOS 打包后的原生视图
        print("App will open as native window (desktop or mobile)...")
        ft.app(
            main,
            assets_dir="assets"
        )
