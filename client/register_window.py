from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QMessageBox

from utils.thread_safe_mixin import ThreadSafeMixin


class RegisterWindow(QWidget, ThreadSafeMixin):
    def __init__(self):
        super().__init__()

        self._threads = []
        self._alive = True

        self.setWindowTitle("Регистрация")
        self.setFixedSize(320, 260)

        self.layout = QVBoxLayout(self)

        self.login = QLineEdit()
        self.login.setPlaceholderText("Логин")

        self.password = QLineEdit()
        self.password.setPlaceholderText("Пароль")
        self.password.setEchoMode(QLineEdit.Password)

        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText("Никнейм")

        self.btn_register = QPushButton("Создать аккаунт")
        self.btn_register.clicked.connect(self.register_user)

        self.layout.addWidget(self.login)
        self.layout.addWidget(self.password)
        self.layout.addWidget(self.nickname)
        self.layout.addWidget(self.btn_register)

    def register_user(self):
        login = self.login.text().strip()
        password = self.password.text()
        nickname = self.nickname.text().strip()

        if not login or not password or not nickname:
            QMessageBox.warning(self, "Ошибка", "Заполни логин, пароль и никнейм")
            return

        self.btn_register.setEnabled(False)

        data = {
            "action": "register",
            "login": login,
            "password": password,
            "nickname": nickname,
            "avatar": ""
        }
        self.start_request(data, self.handle_register_response)

    def handle_register_response(self, resp):
        self.btn_register.setEnabled(True)

        if resp.get("status") == "ok":
            QMessageBox.information(self, "Готово", "Аккаунт успешно создан")
            self.close()
        else:
            QMessageBox.warning(self, "Ошибка", resp.get("message", "Не удалось зарегистрироваться"))

    def closeEvent(self, event):
        self._alive = False
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
