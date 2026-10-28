from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, QMessageBox
from network import NetworkThread
from settings import get_api_endpoint


class RegisterWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.on_registered = None
        self.on_back = None

        self.thread = None
        self.setObjectName("RegisterPage")

        from ui.design.auth import build_auth_layout, field
        from ui.design.widgets import Button
        layout=build_auth_layout(self,'Создать аккаунт','Присоединяйтесь к своим людям')
        self.login=field(layout,'Логин')
        self.nickname=field(layout,'Имя в Nodus')
        self.password=field(layout,'Пароль',True)
        self.password.returnPressed.connect(self.register_user)
        self.status_label=QLabel();self.status_label.setObjectName('ErrorLabel');self.status_label.setWordWrap(True);layout.addWidget(self.status_label)
        layout.addStretch()
        self.btn_register=Button('Создать аккаунт',primary=True);self.btn_register.clicked.connect(self.register_user);layout.addWidget(self.btn_register)
        self.btn_back=Button('Уже есть аккаунт? Войти');self.btn_back.clicked.connect(self.back_to_auth);layout.addWidget(self.btn_back)

    def register_user(self):
        if self.thread and self.thread.isRunning():
            return
        self.btn_register.setEnabled(False)
        self.status_label.setText('Создаём аккаунт…')
        data = {
            "action": "register",
            "login": self.login.text().strip(),
            "password": self.password.text(),
            "nickname": self.nickname.text().strip(),
            "avatar": ""
        }

        host, port = get_api_endpoint()
        self.thread = NetworkThread(host, port, data)
        self.thread.finished.connect(self.handle_register_response)
        self.thread.start()

    def handle_register_response(self, resp):
        self.btn_register.setEnabled(True)
        self.status_label.clear()
        if resp.get("status") == "ok":
            self.status_label.setText("Аккаунт создан. Войдите с новым паролем.")
            self.login.clear(); self.password.clear(); self.nickname.clear()
            if callable(self.on_registered):
                self.on_registered()
        else:
            self.status_label.setText(resp.get("message", "Не удалось зарегистрироваться"))

    def back_to_auth(self):
        if callable(self.on_back):
            self.on_back()
