import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from application.startup_barrier import StartupBarrier


class StartupBarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_waits_for_dependent_reads_and_seal(self):
        barrier = StartupBarrier()
        ready = []
        children = []
        barrier.ready.connect(lambda: ready.append(True))
        first = barrier.track('get_friends', lambda _: children.append(
            barrier.track('get_messages', lambda _: None)))
        barrier.seal()
        first({'status': 'ok'})
        self.app.processEvents()
        self.assertFalse(ready)
        children[0]({'status': 'ok'})
        self.app.processEvents()
        self.assertEqual(ready, [True])

    def test_error_never_releases_main(self):
        barrier = StartupBarrier()
        ready, errors = [], []
        barrier.ready.connect(lambda: ready.append(True))
        barrier.failed.connect(errors.append)
        done = barrier.track('get_friends', lambda _: None)
        barrier.seal()
        done({'status': 'error'})
        self.app.processEvents()
        self.assertFalse(ready)
        self.assertEqual(len(errors), 1)

    def test_cancel_ignores_late_completion(self):
        barrier = StartupBarrier()
        ready = []
        barrier.ready.connect(lambda: ready.append(True))
        done = barrier.track('get_friends', lambda _: None)
        barrier.seal()
        barrier.cancel()
        done({'status': 'ok'})
        self.app.processEvents()
        self.assertFalse(ready)

    def test_timeout_stays_on_startup(self):
        barrier = StartupBarrier()
        errors = []
        barrier.failed.connect(errors.append)
        barrier.track('get_messages', lambda _: None)
        barrier.seal()
        barrier._timeout()
        self.assertEqual(len(errors), 1)
        self.assertFalse(barrier.active)
