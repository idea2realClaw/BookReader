import flet as ft
import datetime
import os

log_file = open("app.log", "a", encoding="utf-8")

def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    print(line, end="")
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
        page.update()

        log("Adding text control...")
        page.add(ft.Text("Hello from BookReader!", size=30, color=ft.Colors.BLUE))
        page.update()
        log("Text added and page updated")
        
        # Keep the app running
        log("App is running...")
        
    except Exception as e:
        log(f"Error in main: {e}")
        import traceback
        traceback.print_exc(file=log_file)
        page.add(ft.Text(f"Error: {e}", color=ft.Colors.RED))
        page.update()


if __name__ == "__main__":
    try:
        log("=" * 50)
        log("Starting BookReader...")
        log(f"Python: {os.sys.version}")
        log(f"Flet: {ft.__version__}")
        ft.run(main, assets_dir="assets")
        log("BookReader exited normally")
    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        traceback.print_exc(file=log_file)
    finally:
        log_file.close()
        log_file = None
