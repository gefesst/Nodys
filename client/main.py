import sys
from PySide6.QtWidgets import QApplication
from app_window import AppWindow
from style_manager import apply_app_styles


def main():
    app = QApplication(sys.argv)
    apply_app_styles(app, "base", "auth", "main", "friends", "chats", "channels", "profile", "call")
    w = AppWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
