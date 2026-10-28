import json
import struct
import threading
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from test_foundation import ROOT
import sys
sys.path.insert(0,str(ROOT/'client'))
from application import session_cleanup


class CleanupTests(unittest.TestCase):
    def test_cleanup_uses_captured_token_without_waiting_for_network(self):
        entered=threading.Event();release=threading.Event();sent=[]
        reply=b'{"status":"ok"}'
        class Socket:
            data=struct.pack('!I',len(reply))+reply
            def sendall(self,data):sent.append(json.loads(data[4:]))
            def settimeout(self,value):pass
            def recv(self,count):
                result=self.data[:count];self.data=self.data[count:];return result
        @contextmanager
        def connection(*args,**kwargs):
            entered.set();release.wait(2)
            yield Socket()
        request=dict(action='logout',login='alice',token='old-token')
        with patch.object(session_cleanup,'connect_api',side_effect=connection):
            future=session_cleanup.submit(('localhost',5555),request)
            self.assertTrue(entered.wait(1))
            request['token']='new-token'
            self.assertFalse(future.done())
            release.set()
            self.assertEqual(future.result(timeout=2),{'status':'ok'})
        self.assertEqual(sent[0]['token'],'old-token')
