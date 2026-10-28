"""Session-scoped call signaling. Owns requests/state, never Qt widgets or audio devices."""
from PySide6.QtCore import QObject, Signal
from network import NetworkThread


class CallController(QObject):
    state_changed = Signal(object)
    notice = Signal(str, int)
    response_finished = Signal(bool)

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

    def reset(self):
        self.generation += 1
        for request in self.requests.values():
            request.abort()
        self.requests.clear()
        self.cursor = 0
        self.state = None
        self._state_key = None
        self.token = getattr(self.context(), 'session_token', '')

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
        key = None if state is None else (state['call_id'], state['peer'], state['status'], state.get('incoming'))
        if key != self._state_key:
            self._state_key = key
            self.state = None if state is None else dict(state)
            self.state_changed.emit(self.state)

    def _refresh_after_action(self):
        # An in-flight read may predate this mutation. Cancel and fence it.
        pending = self.requests.pop('poll', None)
        if pending is not None:
            pending.abort()
        self.generation += 1
        self.poll()

    def start_call(self, peer):
        if not peer:
            return False
        def done(response):
            ok = isinstance(response, dict) and response.get('status') == 'ok'
            self.notice.emit(f'Вызов отправлен пользователю {peer}' if ok else
                             response.get('message', 'Не удалось начать вызов'), 2600)
            self._refresh_after_action()
        return self._request('action', dict(action='call_user', to_user=peer), done)

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
