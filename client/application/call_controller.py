"""Session-scoped call signaling. Owns requests/state, never Qt widgets or audio devices."""
from PySide6.QtCore import QObject, Signal
from network import NetworkThread


class CallController(QObject):
    state_changed = Signal(object)
    notice = Signal(str, int)
    response_finished = Signal(bool)
    result_ready = Signal(object)
    pending_changed = Signal(object)

    def __init__(self, context, parent=None, request_factory=NetworkThread):
        super().__init__(parent)
        self.context = context
        self.request_factory = request_factory
        self.requests = {}
        self.token = None
        self.generation = 0
        self.cursor = 0
        self.state = None
        self._state_key = None
        self.pending_peer = None
        self.cancelled_start = None

    def reset(self):
        self.generation += 1
        for request in self.requests.values():
            request.abort()
        self.requests.clear()
        self.cursor = 0
        self.state = None
        self._state_key = None
        self.token = getattr(self.context(), 'session_token', '')
        self.pending_peer = None
        self.cancelled_start = None
        self.pending_changed.emit(None)

    def _identity(self):
        context = self.context()
        if self.token != context.session_token:
            self.reset()
        return context

    def _request(self, slot, payload, done):
        context = self._identity()
        if not context.login or not context.session_token:
            return False
        pending = self.requests.get(slot)
        if pending is not None and pending.isRunning():
            return False
        generation, token = self.generation, context.session_token
        request = self.request_factory(None, None, dict(payload, login=context.login, token=token))
        self.requests[slot] = request
        def finish(response):
            if self.requests.get(slot) is request:
                self.requests.pop(slot, None)
            if self.generation == generation and self.context().session_token == token:
                done(response if isinstance(response, dict) else {"status":"error", "message":"Некорректный ответ сервера"})
        request.finished.connect(finish)
        request.start()
        return True

    def poll(self):
        self._identity()
        return self._request('poll', dict(action='poll_events', after_event_id=self.cursor), self.receive)

    def receive(self, response):
        if not isinstance(response, dict) or response.get('status') != 'ok' or 'call_state' not in response:
            return
        events = response.get('events', [])
        if not isinstance(events, list):
            return
        previous_cursor = self.cursor
        previous_state = self.state
        for event in events:
            if not isinstance(event, dict):
                continue
            identity = event.get('event_id', 0)
            if type(identity) is int:
                self.cursor = max(self.cursor, identity)
        state = response['call_state']
        if state is not None:
            if not isinstance(state, dict) or state.get('status') not in ('active', 'ringing'):
                return
            if not isinstance(state.get('call_id'), str) or not isinstance(state.get('peer'), str):
                return
        if self.pending_peer is not None and state and state['peer'] == self.pending_peer and not state.get('incoming'):
            # A concurrent poll can observe the mutation before its response.
            # Wait for the action callback and its fresh snapshot, including cancel.
            return
        if self.cancelled_start is not None and self.pending_peer is None:
            cancelled = self.cancelled_start
            self.cancelled_start = None
            if state and state['peer'] == cancelled and not state.get('incoming'):
                # The request reached the server before the user cancelled it.
                # End only this returned call identity, without starting audio/UI.
                self.end_call(state['call_id'], cancelled)
                return
        key = None if state is None else (state['call_id'], state['peer'], state['status'], state.get('incoming'))
        if key != self._state_key:
            self._state_key = key
            self.state = None if state is None else dict(state)
            self.state_changed.emit(self.state)
            if state is None and previous_state is not None:
                terminal = next((event for event in reversed(events)
                    if isinstance(event, dict)
                    and type(event.get("event_id")) is int
                    and event["event_id"] > previous_cursor
                    and event.get("call_id") == previous_state["call_id"]
                    and event.get("with_user") == previous_state["peer"]
                    and event.get("type") in ("call_declined", "call_ended")), None)
                title = "Звонок завершён"
                if terminal and terminal["type"] == "call_declined":
                    title = "Вызов отклонён"
                elif terminal and terminal.get("by_user") == "system":
                    title = "Нет ответа" if previous_state["status"] == "ringing" else "Связь прервана"
                self.result_ready.emit(dict(peer=previous_state["peer"], title=title))

    def _refresh_after_action(self):
        # An in-flight read may predate this mutation. Cancel and fence it.
        pending = self.requests.pop('poll', None)
        if pending is not None:
            pending.abort()
        self.generation += 1
        self.poll()

    def start_call(self, peer):
        if not peer or self.pending_peer is not None or self.cancelled_start is not None:
            return False
        def done(response):
            self.pending_peer = None
            self.pending_changed.emit(None)
            ok = isinstance(response, dict) and response.get('status') == 'ok'
            if not ok:
                cancelled = self.cancelled_start == peer
                self.cancelled_start = None
                if not cancelled:
                    message = response.get("message", "Не удалось начать звонок")
                    title = message if message in ("Пользователь занят", "Пользователь не в сети", "Пользователь не найден", "Можно звонить только друзьям") else "Не удалось начать звонок"
                    self.result_ready.emit(dict(peer=peer, title=title, **({"detail":message} if title!=message else {})))
            self._refresh_after_action()
        started = self._request('action', dict(action='call_user', to_user=peer), done)
        if started:
            self.pending_peer = peer
            self.pending_changed.emit(peer)
        return started

    def cancel_start(self, peer):
        if self.pending_peer == peer:
            self.cancelled_start = peer
            self.pending_changed.emit(None)

    def respond(self, accept):
        state = self.state
        if not state or state['status'] != 'ringing' or not state.get('incoming'):
            return False
        def done(response):
            ok = isinstance(response, dict) and response.get('status') == 'ok'
            self.response_finished.emit(ok)
            if not ok:
                self.notice.emit(response.get('message', 'Не удалось обработать вызов'), 2500)
            self._refresh_after_action()
        return self._request('action', dict(action='accept_call' if accept else 'decline_call',
                                           from_user=state['peer'], call_id=state['call_id']), done)

    def end_call(self, call_id, peer):
        def done(response):
            if response.get('status') != 'ok':
                self.notice.emit(response.get('message', 'Не удалось завершить звонок'), 2500)
            self._refresh_after_action()
        return self._request('action', dict(action='end_call', with_user=peer, call_id=call_id), done)
