from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QMessageBox
from network import NetworkThread
from user_context import UserContext


class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Авторизация")
        self.setFixedSize(300, 200)

        self.ctx = UserContext()
        self.thread = None

        layout = QVBoxLayout(self)

        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Логин")

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setEchoMode(QLineEdit.Password)

        self.btn_login = QPushButton("Войти")
        self.btn_register = QPushButton("Регистрация")

        self.btn_login.clicked.connect(self.login_user)
        self.btn_register.clicked.connect(self.open_register)

        layout.addWidget(self.login_edit)
        layout.addWidget(self.password_edit)
        layout.addWidget(self.btn_login)
        layout.addWidget(self.btn_register)

    # ---------------- Login ----------------

    def login_user(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text().strip()

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль")
            return

        data = {
            "action": "login",
            "login": login,
            "password": password
        }

        self.thread = NetworkThread("127.0.0.1", 5555, data)
        self.thread.finished.connect(self.handle_login_response)
        self.thread.start()

    def handle_login_response(self, resp: dict):
        if resp.get("status") != "ok":
            QMessageBox.warning(self, "Ошибка", resp.get("message", "Ошибка входа"))
            return

        # Сохраняем пользователя в контекст
        self.ctx.set_user(
            login=resp["login"],
            nickname=resp["nickname"],
            avatar_path=resp.get("avatar", "")
        )

        from ui.main_window import MainWindow
        self.main_window = MainWindow()
        self.main_window.show()
        self.close()

    # ---------------- Register ----------------

    def open_register(self):
        from register_window import RegisterWindow
        self.register_window = RegisterWindow()
        self.register_window.show()
