from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, QMessageBox
from network import NetworkThread
from config import save_config
from user_context import UserContext
from settings import get_api_endpoint


class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.ctx = UserContext()

        self.on_login_success = None
        self.on_open_register = None

        self.thread = None

        self.setObjectName("AuthPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(12)

        title = QLabel("Вход в Nodys")
        title.setObjectName("AuthTitle")
        layout.addWidget(title)

        self.login = QLineEdit()
        self.login.setPlaceholderText("Логин")
        layout.addWidget(self.login)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Пароль")
        self.password.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password)

        self.btn_login = QPushButton("Войти")
        self.btn_login.setObjectName("PrimaryButton")
        self.btn_register = QPushButton("Регистрация")

        self.btn_login.clicked.connect(self.login_user)
        self.btn_register.clicked.connect(self.open_register)

        layout.addWidget(self.btn_login)
        layout.addWidget(self.btn_register)
        layout.addStretch()

    def login_user(self):
        data = {
            "action": "login",
            "login": self.login.text().strip(),
            "password": self.password.text()
        }

        host, port = get_api_endpoint()
        self.thread = NetworkThread(host, port, data)
        self.thread.finished.connect(self.handle_login_response)
        self.thread.start()

    def handle_login_response(self, resp):
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
            QMessageBox.warning(self, "Ошибка", resp.get("message", "Неверный логин или пароль"))

    def open_register(self):
        if callable(self.on_open_register):
            self.on_open_register()
