import flet as ft
import datetime
import os
import sys
import threading
import time
import webbrowser

# Global log buffer
log_buffer = []
log_lock = threading.Lock()
log_controls = []

def log(msg):
    """Thread-safe logging function"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with log_lock:
        log_buffer.append(line)
        # Notify all log controls
        for ctrl in log_controls:
            try:
                ctrl.value = "\n".join(log_buffer[-100:])  # Keep last 100 lines
            except:
                pass


def create_debug_page(page: ft.Page):
    """Create a debug window that shows real-time logs"""
    log_text = ft.Text(
        value="Waiting for logs...\n",
        font_family="Consolas",
        size=11,
        color=ft.Colors.GREEN,
        selectable=True,
    )
    
    with log_lock:
        log_controls.append(log_text)
    
    return ft.View(
        route="/debug",
        controls=[
            ft.AppBar(
                title=ft.Text("Debug Log", color=ft.Colors.WHITE),
                bgcolor=ft.Colors.BLACK,
                actions=[
                    ft.IconButton(
                        ft.Icons.REFRESH,
                        tooltip="Refresh",
                        icon_color=ft.Colors.WHITE,
                        on_click=lambda e: page.update()
                    ),
                    ft.IconButton(
                        ft.Icons.CLEAR,
                        tooltip="Clear",
                        icon_color=ft.Colors.WHITE,
                        on_click=lambda e: (
                            log_buffer.clear(),
                            setattr(log_text, 'value', ''),
                            page.update()
                        )
                    ),
                ],
            ),
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=log_text,
                            padding=10,
                            expand=True,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
                bgcolor=ft.Colors.BLACK,
                expand=True,
                padding=5,
            ),
        ],
    )


def main(page: ft.Page):
    try:
        log("=" * 80)
        log("Main function called")
        
        page.title = "BookReader"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 0
        page.window_width = 400
        page.window_height = 700
        
        log("Page configured, creating BookShelf...")
        
        from ui.bookshelf import BookShelf
        shelf = BookShelf(page)
        page.views.append(shelf)
        
        log("BookShelf created, updating page...")
        page.update()
        log("Page updated successfully")
        log("Application started successfully!")
        
    except Exception as e:
        log(f"ERROR in main: {type(e).__name__}: {e}")
        import traceback
        for line in traceback.format_exc().split("\n"):
            if line.strip():
                log(line)


if __name__ == "__main__":
    try:
        log(f"Python version: {sys.version}")
        log(f"Flet version: {ft.__version__}")
        log(f"Working directory: {os.getcwd()}")
        
        # Write logs to file in background
        def write_log_file():
            while True:
                try:
                    with open("debug.log", "w", encoding="utf-8") as f:
                        with log_lock:
                            f.write("\n".join(log_buffer))
                    time.sleep(1)
                except:
                    pass
        
        log_thread = threading.Thread(target=write_log_file, daemon=True)
        log_thread.start()
        
        log("Starting Flet application in WEB mode...")
        log("The app will open in your default browser")
        
        # Run in web browser mode - opens in browser instead of WebView2
        # This avoids WebView2 issues on Windows
        ft.run(main, assets_dir="assets", host="127.0.0.1", port=8550, view=ft.AppView.WEB_BROWSER)
        
        log("Flet application exited")
        
    except Exception as e:
        log(f"FATAL ERROR: {type(e).__name__}: {e}")
        import traceback
        for line in traceback.format_exc().split("\n"):
            if line.strip():
                log(line)
        
        # Write final log to file
        try:
            with open("debug.log", "w", encoding="utf-8") as f:
                with log_lock:
                    f.write("\n".join(log_buffer))
        except:
            pass
        
        input("\nPress Enter to exit...")
