"""Non-blocking detector and serialized presence publishing, independent of widget redraws."""
import time
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QTimer
from config import load_config, save_config
from integrations.steam import detect
from network import NetworkThread

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='noda-steam')


class SteamPresence(QObject):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.enabled = bool(load_config().get('share_steam_activity', True))
        self.future = None
        self.request = None
        self.token = ''
        self.activity = {}
        self.generation = 0
        self.next_scan = 0
        self.next_publish = 0
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.generation += 1
        self.activity = {}
        if self.request is not None:
            self.request.abort()
            self.request = None

    def set_enabled(self, enabled):
        save_config({'share_steam_activity': bool(enabled)})
        self.enabled = bool(enabled)
        self.generation += 1
        self.activity = {}
        self.next_scan = self.next_publish = 0
        self.tick()

    def tick(self):
        if not self.timer.isActive():
            return
        token = self.main.ctx.session_token
        if token != self.token:
            self.token = token
            self.generation += 1
            self.activity = {}
            self.next_scan = self.next_publish = 0
        if not token or self.main.is_logging_out or self.main._is_closing:
            return
        now = time.monotonic()
        if self.future is not None and self.future.done():
            try:
                result = self.future.result()
            except Exception:
                result = {}
            self.future = None
            if self.scan_generation == self.generation and self.enabled:
                if result != self.activity:
                    self.next_publish = 0
                self.activity = result
        if self.enabled and self.future is None and now >= self.next_scan:
            self.scan_generation = self.generation
            self.future = _executor.submit(detect)
            self.next_scan = now + 5
        if now >= self.next_publish and self.request is None:
            payload = dict(action='heartbeat', token=token,
                           activity_sequence=time.time_ns()//1000,
                           steam_nickname='', steam_game='', steam_app_id='')
            payload.update(self.activity if self.enabled else {})
            self.request = NetworkThread(None, None, payload)
            request = self.request
            request.finished.connect(lambda response, request=request: self.finished(request, response))
            self.next_publish = now + 15
            self.request.start()

    def finished(self, request, response):
        if request is not self.request:
            return
        self.request = None
        self.tick()  # A pending disable is published as soon as an older request finishes.
