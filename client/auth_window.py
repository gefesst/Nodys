from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QMessageBox

from utils.thread_safe_mixin import ThreadSafeMixin


class AuthWindow(QWidget, ThreadSafeMixin):
    def __init__(self, on_login_success=None, controller=None):
        super().__init__()
        self.on_login_success = on_login_success
        self.controller = controller

        self._threads = []
        self._alive = True

        self.setWindowTitle("Авторизация")
        self.setFixedSize(320, 220)

        layout = QVBoxLayout(self)

        self.login = QLineEdit()
        self.login.setPlaceholderText("Логин")

        self.password = QLineEdit()
        self.password.setPlaceholderText("Пароль")
        self.password.setEchoMode(QLineEdit.Password)

        btn_login = QPushButton("Войти")
        btn_register = QPushButton("Регистрация")

        btn_login.clicked.connect(self.login_user)
        btn_register.clicked.connect(self.open_register)

        layout.addWidget(self.login)
        layout.addWidget(self.password)
        layout.addWidget(btn_login)
        layout.addWidget(btn_register)

    def login_user(self):
        data = {
            "action": "login",
            "login": self.login.text().strip(),
            "password": self.password.text()
        }
        self.start_request(data, self.handle_login_response)

    def handle_login_response(self, resp):
        if resp.get("status") == "ok":
            login = resp.get("login", "")
            nickname = resp.get("nickname", "")
            if callable(self.on_login_success):
                self.on_login_success(login, nickname)
        else:
            QMessageBox.warning(self, "Ошибка", resp.get("message", "Неверный логин или пароль"))

    def open_register(self):
        from register_window import RegisterWindow
        self.reg = RegisterWindow()
        self.reg.show()

    def closeEvent(self, event):
        self._alive = False
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
