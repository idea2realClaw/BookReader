import flet as ft
import datetime
import os
import sys

# Force stdout/stderr to be unbuffered
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)

log_file = open("app.log", "a", encoding="utf-8")

def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    sys.stdout.write(line)
    log_file.write(line)
    log_file.flush()


def main(page: ft.Page):
    try:
        log("Main function called")
        page.title = "BookReader"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 0
        page.window_width = 800
        page.window_height = 600
        page.window_resizable = True

        log("Creating UI...")
        from ui.bookshelf import BookShelf
        shelf = BookShelf(page)
        page.views.append(shelf)
        page.update()
        log("UI created and page updated successfully")
        
    except Exception as e:
        log(f"Error in main: {e}")
        import traceback
        traceback.print_exc(file=log_file)
        try:
            page.add(ft.Text(f"Error: {e}", color=ft.Colors.RED, size=14))
            page.update()
        except:
            pass


if __name__ == "__main__":
    try:
        log("=" * 60)
        log(f"Starting BookReader...")
        log(f"Python: {sys.version}")
        log(f"Flet: {ft.__version__}")
        log(f"Working directory: {os.getcwd()}")
        
        # Run the app
        # Note: Flet 0.85 doesn't support view=WEB_BROWSER parameter
        # It will use WebView2 on Windows by default
        ft.run(main, assets_dir="assets")
        log("BookReader exited normally")
        
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        traceback.print_exc(file=log_file)
        input("Press Enter to exit...")
        
    finally:
        try:
            log_file.close()
        except:
            pass
