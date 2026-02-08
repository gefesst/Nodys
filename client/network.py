import socket
import json
import threading
from PySide6.QtCore import QObject, Signal


class NetworkThread(QObject):
    """
    Drop-in замена старого QThread-класса.
    API совместим с текущим кодом:
    - finished (Signal(dict))
    - start()
    - isRunning()
    - wait(ms)
    - abort()
    - requestInterruption()
    - quit()
    """
    finished = Signal(dict)

    def __init__(self, host, port, data):
        super().__init__()
        self.host = host
        self.port = port
        self.data = data

        self._abort_event = threading.Event()
        self._thread = None

    # ---------------- compatibility API ----------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def isRunning(self):
        return self._thread is not None and self._thread.is_alive()

    def wait(self, ms=0):
        if not self._thread:
            return True
        timeout = None if ms is None or ms <= 0 else ms / 1000.0
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    def abort(self):
        self._abort_event.set()

    def requestInterruption(self):
        self.abort()

    def quit(self):
        self.abort()

    # ---------------- internal ----------------
    def _emit_if_alive(self, payload: dict):
        if not self._abort_event.is_set():
            self.finished.emit(payload)

    def _run(self):
        if self._abort_event.is_set():
            return

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)

                s.connect((self.host, self.port))
                if self._abort_event.is_set():
                    return

                payload = json.dumps(self.data).encode("utf-8")
                s.sendall(payload)
                if self._abort_event.is_set():
                    return

                resp = s.recv(65536)
                if self._abort_event.is_set():
                    return

                if not resp:
                    self._emit_if_alive({"status": "error", "message": "Пустой ответ от сервера"})
                    return

                try:
                    obj = json.loads(resp.decode("utf-8"))
                except json.JSONDecodeError:
                    self._emit_if_alive({"status": "error", "message": "Некорректный JSON от сервера"})
                    return

                self._emit_if_alive(obj)

        except socket.timeout:
            self._emit_if_alive({"status": "error", "message": "Таймаут сети"})
        except ConnectionRefusedError:
            self._emit_if_alive({"status": "error", "message": "Сервер не запущен"})
        except OSError as e:
            self._emit_if_alive({"status": "error", "message": f"Ошибка сокета: {e}"})
        except Exception as e:
            self._emit_if_alive({"status": "error", "message": f"Ошибка сети: {e}"})
