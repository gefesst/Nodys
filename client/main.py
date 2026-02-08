import sys
import json
import traceback
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject

from auth_window import AuthWindow
from ui.main_window import MainWindow
from user_context import UserContext

CONFIG_FILE = "config.json"
APP_CONTROLLER = None


def excepthook(exc_type, exc, tb):
    print("UNCAUGHT EXCEPTION:")
    traceback.print_exception(exc_type, exc, tb)


sys.excepthook = excepthook


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class AppController(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.auth_window = None
        self.main_window = None

    def show_auth(self):
        if self.main_window is not None:
            self.main_window.hide()

        if self.auth_window is None:
            self.auth_window = AuthWindow(on_login_success=self.show_main, controller=self)

        self.auth_window.show()
        self.auth_window.raise_()
        self.auth_window.activateWindow()

    def show_main(self, login: str, nickname: str):
        ctx = UserContext()
        ctx.login = login
        ctx.nickname = nickname

        if self.main_window is None:
            self.main_window = MainWindow(controller=self)

        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

        if self.auth_window is not None:
            self.auth_window.hide()

    def logout_to_auth(self):
        self.show_auth()

    def quit_app(self):
        self.app.quit()


def main():
    global APP_CONTROLLER

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    APP_CONTROLLER = AppController(app)

    cfg = load_config()
    ctx = UserContext()
    if cfg.get("login"):
        ctx.login = cfg.get("login", "")
        ctx.nickname = cfg.get("nickname", "")
        ctx.avatar_path = cfg.get("avatar", "")

    if ctx.login:
        APP_CONTROLLER.show_main(ctx.login, ctx.nickname)
    else:
        APP_CONTROLLER.show_auth()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
