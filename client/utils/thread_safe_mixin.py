class ThreadSafeMixin:
    """Универсальный mixin для безопасной работы с NetworkThread (threading-based).

    Ожидает:
    - self._threads: list
    - self._alive: bool
    """

    def start_request(self, data, callback, host=None, port=None):
        from network import NetworkThread, AUTH_ACTIONS  # локальный импорт, чтобы избежать циклов

        if not getattr(self, "_alive", True):
            return

        payload = dict(data or {})
        action = payload.get("action")

        # Локальная привязка к контексту страницы/окна.
        # Это помогает при нескольких окнах приложения в одном процессе:
        # запросы идут с токеном/логином именно этой страницы.
        ctx = getattr(self, "ctx", None)
        if ctx is not None and action in AUTH_ACTIONS:
            token = getattr(ctx, "session_token", "")
            login = getattr(ctx, "login", "")

            if token and "token" not in payload:
                payload["token"] = token

            if "login" not in payload and login:
                payload["login"] = login

            # from_user должен автозаполняться только там,
            # где это действительно "текущий пользователь".
            if action in {"send_friend_request", "send_message", "call_user", "get_messages"}:
                if "from_user" not in payload and login:
                    payload["from_user"] = login

        t = NetworkThread(host, port, payload)
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
