import socket
import json
from PySide6.QtCore import QThread, Signal

class NetworkThread(QThread):
    finished = Signal(dict)

    def __init__(self, host, port, data):
        super().__init__()
        self.host = host
        self.port = port
        self.data = data

    def run(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                s.sendall(json.dumps(self.data).encode())
                resp = s.recv(4096)
                if not resp:
                    self.finished.emit({"status":"error","message":"Пустой ответ от сервера"})
                    return
                self.finished.emit(json.loads(resp.decode()))
        except Exception as e:
            # вместо crash, эмитим ошибку
            self.finished.emit({"status":"error","message":f"Ошибка сети: {e}"})

