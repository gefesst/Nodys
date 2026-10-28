"""Network completions must outlive their worker and run only on the GUI thread."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from application.qt_runtime import prepare_platform_plugins
prepare_platform_plugins()
from PySide6.QtWidgets import QApplication
from network import NetworkThread

class NetworkDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_platform_plugins()
        cls.app=QApplication.instance() or QApplication([])
    def spin(self, predicate):
        deadline=time.monotonic()+2
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.001)
        self.assertTrue(predicate())
    def test_worker_completion_is_retained_and_delivered_on_gui(self):
        callbacks=[];workers=[]
        request=NetworkThread('localhost',1,{'action':'status'})
        request.finished.connect(lambda value:callbacks.append(threading.get_ident()))
        def run():
            workers.append(threading.get_ident())
            request._emit_if_alive({'status':'ok'})
        with patch.object(request,'_run',side_effect=run):
            request.start()
            self.spin(lambda:len(callbacks)==1 and request not in NetworkThread._inflight)
        self.assertNotEqual(workers[0],threading.get_ident())
        self.assertEqual(callbacks,[threading.get_ident()])
    def test_abort_after_queueing_suppresses_completion(self):
        callbacks=[];request=NetworkThread('localhost',1,{'action':'status'})
        request.finished.connect(callbacks.append)
        worker=threading.Thread(target=lambda:request._emit_if_alive({'status':'ok'}))
        worker.start();worker.join(1);request.abort()
        self.app.processEvents()
        self.assertEqual(callbacks,[])

    def test_completed_request_is_destroyed_on_gui_after_delivery(self):
        from PySide6.QtCore import QCoreApplication, QEvent, Qt
        from shiboken6 import isValid
        events = []
        request = NetworkThread('localhost', 1, {'action': 'status'})
        self.assertIs(request.parent(), self.app)
        request.finished.connect(lambda _: events.append(('delivered', threading.get_ident())))
        request.destroyed.connect(lambda: events.append(('destroyed', threading.get_ident())), Qt.DirectConnection)
        with patch.object(request, '_run', side_effect=lambda: request._emit_if_alive({'status': 'ok'})):
            request.start()
            self.spin(lambda: request not in NetworkThread._inflight)
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(request))
        self.assertEqual(events, [('delivered', threading.get_ident()), ('destroyed', threading.get_ident())])
