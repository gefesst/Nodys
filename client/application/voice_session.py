"""Qt-facing voice lifecycle; network/device work stays off the UI thread."""
from concurrent.futures import ThreadPoolExecutor
import threading
from PySide6.QtCore import QObject, Signal, Slot, Qt, QCoreApplication, QTimer
from voice_client import VoiceClient

# One audio-device owner at a time: old stop completes before a new start.
_lifecycle = ThreadPoolExecutor(max_workers=1, thread_name_prefix='nodys-voice-lifecycle')


class VoiceSession(QObject):
    ready = Signal()
    failed = Signal(str)
    _completed = Signal(object)
    _settled = Signal()

    def __init__(self, login, token='', host='127.0.0.1', port=5556):
        super().__init__(QCoreApplication.instance())
        self._arguments = dict(login=login, token=token, host=host, port=port)
        self._cancelled = threading.Event()
        self._core = None
        self._stop_future = None
        self._started = False
        self.running = False
        self._mic = True
        self._sound = True
        self._completed.connect(self._deliver, Qt.QueuedConnection)
        self._settled.connect(self._release, Qt.QueuedConnection)

    def start(self, peer_login=None, room_id=None):
        if self._started or self._cancelled.is_set():
            return
        self._started = True
        self.running = True  # includes connecting, preventing concurrent joins
        _lifecycle.submit(self._start, peer_login, room_id)

    def _start(self, peer, room):
        if self._cancelled.is_set():
            return
        core = None
        try:
            core = VoiceClient(**self._arguments)
            self._core = core
            core.set_mic_enabled(self._mic)
            core.set_sound_enabled(self._sound)
            core.start(peer_login=peer, room_id=room, cancel_event=self._cancelled)
            if self._cancelled.is_set():
                core.stop()
                return
            core.set_mic_enabled(self._mic)
            core.set_sound_enabled(self._sound)
            self._completed.emit(None)
        except Exception as error:
            if core:
                core.stop()
            if not self._cancelled.is_set():
                self._completed.emit(str(error))

    @Slot(object)
    def _deliver(self, error):
        if self._cancelled.is_set():
            return
        if error is None:
            self.ready.emit()
        else:
            self.running = False
            self.failed.emit(error)

    def stop(self):
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        self.running = False
        self._stop_future = _lifecycle.submit(self._stop)

    def _stop(self):
        try:
            if self._core:
                self._core.stop()
        finally:
            try:
                self._settled.emit()
            except RuntimeError:
                pass  # QApplication teardown already destroyed the wrapper.

    @Slot()
    def _release(self):
        if self._stop_future is None or not self._stop_future.done():
            QTimer.singleShot(0, self._release)
            return
        self.deleteLater()

    def set_mic_enabled(self, enabled):
        self._mic = bool(enabled)
        if self._core:
            self._core.set_mic_enabled(enabled)

    def set_sound_enabled(self, enabled):
        self._sound = bool(enabled)
        if self._core:
            self._core.set_sound_enabled(enabled)

    def get_activity(self):
        if self._core and self._core.running:
            return self._core.get_activity()
        return dict(quality='Подключение',quality_score=0,mic_level=0,peer_level=0,
                    me_speaking=False,peer_speaking=False,latency_ms=0,jitter_ms=0)

    def get_diagnostics(self):
        return self._core.get_diagnostics() if self._core else {'state':'Подключение'}
