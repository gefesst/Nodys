class ThreadSafeMixin:
    """
    Универсальный mixin для безопасной работы с NetworkThread (threading-based).
    Ожидает:
    - self._threads: list
    - self._alive: bool
    """
    def start_request(self, data, callback, host="127.0.0.1", port=5555):
        from network import NetworkThread  # локальный импорт, чтобы избежать циклов

        if not getattr(self, "_alive", True):
            return

        t = NetworkThread(host, port, data)
        self._threads.append(t)

        def done(resp):
            if not getattr(self, "_alive", True):
                if t in self._threads:
                    self._threads.remove(t)
                return

            try:
                callback(resp)
            finally:
                if t in self._threads:
                    self._threads.remove(t)

        t.finished.connect(done)
        t.start()

    def shutdown_requests(self, wait_ms=2000):
        for t in list(getattr(self, "_threads", [])):
            try:
                if hasattr(t, "abort"):
                    t.abort()
                t.requestInterruption()
                if t.isRunning():
                    t.wait(wait_ms)
            except Exception:
                pass

        self._threads = [t for t in self._threads if t.isRunning()]
