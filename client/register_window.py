from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QMessageBox
from network import NetworkThread

class RegisterWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Регистрация")
        self.setFixedSize(300,250)
        self.layout = QVBoxLayout()

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
        self.setLayout(self.layout)
        self.thread = None

    def register_user(self):
        data = {
            "action":"register",
            "login":self.login.text(),
            "password":self.password.text(),
            "nickname":self.nickname.text(),
            "avatar":""
        }
        self.thread = NetworkThread("127.0.0.1",5555,data)
        self.thread.finished.connect(self.handle_register_response)
        self.thread.start()

    def handle_register_response(self, resp):
        if resp.get("status")=="ok":
            QMessageBox.information(self,"Готово","Аккаунт успешно создан")
            self.close()
        else:
            QMessageBox.warning(self,"Ошибка",resp.get("message","Не удалось зарегистрироваться"))
