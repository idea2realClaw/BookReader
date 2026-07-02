import flet as ft
import os
import sys
import argparse


def main(page: ft.Page):
    """主应用入口"""
    page.title = "BookReader"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    
    # 根据视图模式设置窗口大小
    if page.web:
        # 浏览器模式：使用全屏或较大尺寸
        page.window_width = 1200
        page.window_height = 800
    else:
        # 桌面模式：使用更大的窗口尺寸（平板模式）
        page.window_width = 1000
        page.window_height = 800
        page.window_resizable = True
    
    # 导入并创建书架
    from ui.bookshelf import BookShelf
    shelf = BookShelf(page)
    page.views.append(shelf)
    page.update()


if __name__ == "__main__":
    # 命令行参数解析
    parser = argparse.ArgumentParser(description="BookReader - 跨平台电子书阅读器")
    parser.add_argument(
        "--mode",
        choices=["desktop", "browser"],
        default="browser",
        help="运行模式: desktop (桌面应用) 或 browser (浏览器模式, 默认)"
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
        ft.run(
            main,
            assets_dir="assets",
            host=args.host,
            port=args.port,
            view=ft.AppView.WEB_BROWSER
        )
    else:
        print("App will open as desktop window...")
        ft.run(
            main,
            assets_dir="assets"
        )
