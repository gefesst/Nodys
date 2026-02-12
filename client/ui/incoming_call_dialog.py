
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from network import NetworkThread


class IncomingCallDialog(QDialog):
    def __init__(self, current_login: str, from_user: str, parent=None, on_result=None):
        super().__init__(parent)
        self.current_login = current_login
        self.from_user = from_user
        self.on_result = on_result
        self.thread = None

        self.setWindowTitle("Входящий вызов")
        self.setFixedSize(320, 170)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Вам звонит: {from_user}"))
        layout.addWidget(QLabel("Принять вызов?"))

        row = QHBoxLayout()
        self.btn_accept = QPushButton("Принять")
        self.btn_decline = QPushButton("Отклонить")
        row.addWidget(self.btn_accept)
        row.addWidget(self.btn_decline)
        layout.addLayout(row)

        self.btn_accept.clicked.connect(self.accept_call)
        self.btn_decline.clicked.connect(self.decline_call)

    def accept_call(self):
        self.thread = NetworkThread("127.0.0.1", 5555, {"action":"accept_call","login":self.current_login,"from_user":self.from_user})
        self.thread.finished.connect(lambda resp: self._finish("accepted", resp, True))
        self.thread.start()

    def decline_call(self):
        self.thread = NetworkThread("127.0.0.1", 5555, {"action":"decline_call","login":self.current_login,"from_user":self.from_user})
        self.thread.finished.connect(lambda resp: self._finish("declined", resp, False))
        self.thread.start()

    def _finish(self, result, resp, accepted):
        if self.on_result:
            self.on_result(result, resp)
        if accepted:
            self.accept()
        else:
            self.reject()
