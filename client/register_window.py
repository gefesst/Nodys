from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, QMessageBox
from network import NetworkThread


class RegisterWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.on_registered = None
        self.on_back = None

        self.thread = None
        self.setObjectName("RegisterPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(12)

        title = QLabel("Регистрация")
        title.setObjectName("RegisterTitle")
        layout.addWidget(title)

        self.login = QLineEdit()
        self.login.setPlaceholderText("Логин")
        layout.addWidget(self.login)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Пароль")
        self.password.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password)

        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText("Никнейм")
        layout.addWidget(self.nickname)

        self.btn_register = QPushButton("Создать аккаунт")
        self.btn_register.setObjectName("PrimaryButton")
        self.btn_back = QPushButton("Назад ко входу")

        self.btn_register.clicked.connect(self.register_user)
        self.btn_back.clicked.connect(self.back_to_auth)

        layout.addWidget(self.btn_register)
        layout.addWidget(self.btn_back)
        layout.addStretch()

    def register_user(self):
        data = {
            "action": "register",
            "login": self.login.text().strip(),
            "password": self.password.text(),
            "nickname": self.nickname.text().strip(),
            "avatar": ""
        }

        self.thread = NetworkThread("127.0.0.1", 5555, data)
        self.thread.finished.connect(self.handle_register_response)
        self.thread.start()

    def handle_register_response(self, resp):
        if resp.get("status") == "ok":
            QMessageBox.information(self, "Готово", "Аккаунт успешно создан")
            self.login.clear(); self.password.clear(); self.nickname.clear()
            if callable(self.on_registered):
                self.on_registered()
        else:
            QMessageBox.warning(self, "Ошибка", resp.get("message", "Не удалось зарегистрироваться"))

    def back_to_auth(self):
        if callable(self.on_back):
            self.on_back()
