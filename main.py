"""
主窗口布局：管理内容区域和日志窗口
"""
import flet as ft
import time
from version import APP_VERSION
from ui.bookshelf import BookShelf
from ui.log_window import LogWindow


class MainWindow(ft.Column):
    """主窗口：包含内容区域和可折叠的日志窗口"""
    
    def __init__(self, page: ft.Page):
        super().__init__(expand=True, spacing=0)
        
        self.ft_page = page
        
        # 创建日志窗口
        self.log_window = LogWindow(page, max_height=200)
        
        # 创建书架（主内容）
        self.bookshelf = BookShelf(self)
        
        # 创建内容容器（用于切换内容）
        self.content_container = ft.Container(
            content=self.bookshelf,
            expand=True,
        )
        
        # 创建分隔线
        self.divider = ft.Divider(height=2, color=ft.Colors.GREY_300)
        
        # 主布局
        self.controls = [
            self.content_container,
            self.divider,
            self.log_window,
        ]
        
        # 设置日志捕获
        self.log_window.setup_log_capture()
        
        print("[MainWindow] 主窗口已初始化")
    
    def navigate_to_viewer(self, viewer):
        """导航到书籍阅读器"""
        print(f"[MainWindow] 导航到阅读器")
        self.content_container.content = viewer
        self.ft_page.update()
    
    def navigate_to_shelf(self):
        """导航回书架"""
        print(f"[MainWindow] 导航回书架")
        self.content_container.content = self.bookshelf
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
