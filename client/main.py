import sys
from PySide6.QtWidgets import QApplication

from config import load_config
from user_context import UserContext
from auth_window import AuthWindow
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    cfg = load_config()
    ctx = UserContext()

    # Если есть сохранённый вход — поднимаем контекст и открываем MainWindow
    if cfg.get("logged_in") and cfg.get("login"):
        ctx.set_user(
            login=cfg.get("login", ""),
            nickname=cfg.get("nickname", ""),
            avatar_path=cfg.get("avatar", "")
        )
        window = MainWindow()
        window.show()
    else:
        auth = AuthWindow()
        auth.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
