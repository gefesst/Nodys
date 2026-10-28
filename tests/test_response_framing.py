import socket
import struct
import sys
import threading
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from transport.framing import receive

class ResponseFramingTests(unittest.TestCase):
    def test_non_object_and_oversize_responses_rejected(self):
        for payload in (b'[]',b'null',b'{"value":NaN}',b'"wrong"'):
            left,right=socket.socketpair()
            try:
                right.sendall(struct.pack('!I',len(payload))+payload)
                with self.assertRaises(ValueError):receive(left)
            finally:left.close();right.close()
        left,right=socket.socketpair()
        try:
            right.sendall(struct.pack('!I',10_000_001))
            with self.assertRaises(ValueError):receive(left)
        finally:left.close();right.close()
    def test_slow_response_has_total_deadline(self):
        left,right=socket.socketpair();stop=threading.Event()
        def trickle():
            try:
                right.sendall(struct.pack('!I',100))
                while not stop.wait(.01):right.sendall(b' ')
            except OSError:pass
        worker=threading.Thread(target=trickle);worker.start()
        start=time.monotonic()
        try:
            with self.assertRaises(TimeoutError):receive(left,timeout=.08)
            self.assertLess(time.monotonic()-start,.5)
        finally:stop.set();worker.join(1);left.close();right.close()
