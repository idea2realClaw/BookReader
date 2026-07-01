import flet as ft
from ui.bookshelf import BookShelf


def main(page: ft.Page):
    page.title = "BookReader"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window_width = 400
    page.window_height = 700

    shelf = BookShelf(page)
    page.views.append(shelf)
    page.update()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
