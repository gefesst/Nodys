"""Collect Python reference cycles on the Qt thread, never in network workers.

Qt wrapper cycles can otherwise be finalized by whichever Python thread crosses
an allocation threshold while Qt is concurrently painting/deleting native state.
Reference counting remains enabled; cyclic collection runs on a bounded timer.
"""
import gc
from PySide6.QtCore import QObject, QTimer, QThread


class GuiGarbageCollector(QObject):
    def __init__(self, application):
        super().__init__(application)
        gc.disable()
        self.ticks = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.collect)
        self.timer.start()
        application.aboutToQuit.connect(self.timer.stop)

    def collect(self, full=False):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Qt wrapper collection must run on the GUI thread')
        self.ticks += 1
        generation = 2 if full or self.ticks % 30 == 0 else (1 if self.ticks % 10 == 0 else 0)
        gc.collect(generation)


def install(application):
    application._nodus_gc = GuiGarbageCollector(application)
