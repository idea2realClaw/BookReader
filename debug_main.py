import flet as ft
from ui.bookshelf import BookShelf


def main(page: ft.Page):
    page.title = "BookReader"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window_width = 400
    page.window_height = 700

    try:
        shelf = BookShelf(page)
        page.views.append(shelf)
        page.update()
        print("BookShelf created and added to page")
    except Exception as e:
        print(f"Error creating BookShelf: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        ft.run(main, assets_dir="assets")
    except Exception as e:
        print(f"Error running app: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
