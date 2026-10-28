"""Qt remains responsive while voice startup waits; cancelled starts stay closed."""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch
from test_foundation import ROOT
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(ROOT/'client'))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from application.qt_runtime import prepare_platform_plugins
from application.voice_session import VoiceSession, _lifecycle


class FakeVoice:
    def __init__(self, gate, trace):
        self.gate=gate
        self.trace=trace
        self.running=False
        self.entered=threading.Event()
        self.stopped=threading.Event()
    def start(self, **kwargs):
        self.trace.append('start')
        self.entered.set()
        self.gate.wait(2)
        self.running=True
    def stop(self):
        self.trace.append('stop')
        self.running=False
        self.stopped.set()
    def set_mic_enabled(self, value):pass
    def set_sound_enabled(self, value):pass


class VoiceSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_platform_plugins()
        cls.app=QApplication.instance() or QApplication([])

    def pump_until(self, predicate, timeout=2):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.001)
        self.assertTrue(predicate())

    def test_cancel_during_start_does_not_block_qt_or_emit_ready(self):
        gate=threading.Event();fake=FakeVoice(gate,[])
        session=VoiceSession('alice')
        self.addCleanup(session.stop);self.addCleanup(gate.set)
        ready=[];session.ready.connect(lambda:ready.append(True))
        ticks=[];timer=QTimer();timer.setInterval(1);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        self.addCleanup(timer.stop)
        with patch('application.voice_session.VoiceClient',return_value=fake):
            session.start(room_id=1)
            self.pump_until(fake.entered.is_set)
            self.pump_until(lambda:len(ticks)>=3)
            session.stop()
            self.assertFalse(session.running)
            gate.set()
            self.pump_until(fake.stopped.is_set)
            _lifecycle.submit(lambda:None).result(timeout=2)
            self.app.processEvents()
        self.assertEqual(ready,[])

    def test_ready_is_delivered_on_ui_thread(self):
        gate=threading.Event();gate.set()
        fake=FakeVoice(gate,[]);session=VoiceSession('alice')
        self.addCleanup(session.stop)
        threads=[];session.ready.connect(lambda:threads.append(threading.get_ident()))
        with patch('application.voice_session.VoiceClient',return_value=fake):
            session.start(peer_login='bob')
            self.pump_until(lambda:bool(threads))
        self.assertEqual(threads,[threading.get_ident()])
        session.stop();_lifecycle.submit(lambda:None).result(timeout=2)

    def test_constructor_failure_reaches_ui(self):
        session=VoiceSession('alice');self.addCleanup(session.stop)
        errors=[];session.failed.connect(errors.append)
        with patch('application.voice_session.VoiceClient',side_effect=RuntimeError('device failure')):
            session.start(room_id=1)
            self.pump_until(lambda:bool(errors))
        self.assertFalse(session.running)
        self.assertEqual(errors,['device failure'])

    def test_stopped_session_is_destroyed_on_gui_after_worker_finishes(self):
        from PySide6.QtCore import QCoreApplication, QEvent, Qt
        from shiboken6 import isValid
        session = VoiceSession('alice')
        self.assertIs(session.parent(), self.app)
        destroyed = []
        session.destroyed.connect(lambda: destroyed.append(threading.get_ident()), Qt.DirectConnection)
        session.stop()
        _lifecycle.submit(lambda: None).result(timeout=2)
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(session))
        self.assertEqual(destroyed, [threading.get_ident()])
