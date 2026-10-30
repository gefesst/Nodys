from PySide6.QtWidgets import QWidget, QLabel
from network import NetworkThread
from config import save_config
from user_context import UserContext


class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.ctx = UserContext()

        self.on_login_success = None
        self.on_open_register = None

        self.thread = None

        self.setObjectName("AuthPage")

        from ui.design.auth import build_auth_layout, field, finish_auth_layout
        from ui.design.widgets import Button
        layout = build_auth_layout(self, 'С возвращением', 'Ваше место для общения')
        self.login = field(layout, 'Логин')
        self.password = field(layout, 'Пароль', True)
        self.password.returnPressed.connect(self.login_user)
        self.login.returnPressed.connect(lambda:self.password.setFocus())
        self.status_label=QLabel();self.status_label.setObjectName('ErrorLabel');self.status_label.setWordWrap(True)
        self.btn_login=Button('Войти',primary=True);self.btn_login.clicked.connect(self.login_user)
        self.btn_register=Button('Нет аккаунта? Регистрация');self.btn_register.setProperty('flat',True);self.btn_register.clicked.connect(self.open_register)
        finish_auth_layout(layout,self.status_label,self.btn_login,self.btn_register)

    def login_user(self):
        if self.thread and self.thread.isRunning():
            return
        self.status_label.setText("Входим…")
        self.btn_login.setEnabled(False)
        self.btn_register.setEnabled(False)
        data = {
            "action": "login",
            "login": self.login.text().strip(),
            "password": self.password.text()
        }

        self.thread = NetworkThread(None, None, data)
        self.thread.finished.connect(self.handle_login_response)
        self.thread.start()

    def handle_login_response(self, resp):
        self.status_label.clear()
        self.btn_login.setEnabled(True)
        self.btn_register.setEnabled(True)
        if resp.get("status") == "ok":
            login = resp.get("login", "")
            nickname = resp.get("nickname", "")
            avatar = resp.get("avatar", "")
            token = resp.get("token", "")
            expires_at = resp.get("expires_at", "")

            self.ctx.set_user(login=login, nickname=nickname, avatar=avatar, session_token=token, token_expires_at=expires_at)
            save_config({"login": login, "nickname": nickname, "avatar": avatar, "token": token, "token_expires_at": expires_at})

            self.password.clear()

            if callable(self.on_login_success):
                self.on_login_success()
        else:
            self.status_label.setText(resp.get("message", "Неверный логин или пароль"))

    def open_register(self):
        if callable(self.on_open_register):
            self.on_open_register()
