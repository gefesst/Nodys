import json
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch
from test_foundation import load
from protocol.requests import validate
from server_transport.admission import WindowLimiter, Admission
from server_transport.framing import receive


class RequestSecurityTests(unittest.TestCase):
    def test_invalid_envelopes_and_fields_are_rejected(self):
        for payload in ([],None,'login',{'action':[]},{'action':'login','password':{}},
                {'action':'login','password':'x'*1025},{'action':'get_messages','limit':True},
                {'action':'get_messages','limit':501},{'action':'leave_channel','channel_id':-1},
                {'action':'login','token':['x']},{'action':'heartbeat','unexpected':'field'}):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(ValueError):validate(payload)

    def test_ticket_optional_fields_and_unicode_text(self):
        validate(dict(action='voice_ticket',room='channel:1',peer=None,token='test'))
        validate(dict(action='send_message',to_user='bob',text='Привет\n🌍',token='test'))

    def exchange(self, payload):
        left,right=socket.socketpair()
        self.addCleanup(left.close);self.addCleanup(right.close)
        right.sendall(struct.pack('!I',len(payload))+payload)
        return receive(left)

    def test_duplicate_keys_nan_and_non_json_are_rejected(self):
        for payload in (b'{"action":"login","action":"register"}',b'{"action":"login","limit":NaN}',b'broken'):
            with self.assertRaises(ValueError):self.exchange(payload)

    def test_oversized_header_rejected_without_reading_body(self):
        left,right=socket.socketpair()
        try:
            right.sendall(struct.pack('!I',256001))
            with self.assertRaises(ValueError):receive(left)
        finally:left.close();right.close()

    def test_slow_stream_cannot_reset_absolute_deadline(self):
        left,right=socket.socketpair()
        done=threading.Event()
        def trickle():
            try:
                right.sendall(struct.pack('!I',100))
                while not done.wait(.01):right.sendall(b' ')
            except OSError:pass
        worker=threading.Thread(target=trickle);worker.start()
        started=time.monotonic()
        try:
            with self.assertRaises(TimeoutError):receive(left,timeout=.08)
            self.assertLess(time.monotonic()-started,.5)
        finally:
            done.set();worker.join(1);left.close();right.close()

    def test_limiter_expiry_and_memory_bound(self):
        stamp=[0]
        limiter=WindowLimiter(2,60,max_keys=2,clock=lambda:stamp[0])
        self.assertTrue(limiter.allow('a'));self.assertTrue(limiter.allow('a'))
        self.assertFalse(limiter.allow('a'))
        self.assertTrue(limiter.allow('b'));self.assertFalse(limiter.allow('c'))
        stamp[0]=61
        self.assertTrue(limiter.allow('c'));self.assertTrue(limiter.allow('a'))
        self.assertLessEqual(len(limiter.entries),2)

    def test_auth_limit_cannot_be_bypassed_by_changing_login(self):
        admission=Admission()
        for number in range(30):self.assertTrue(admission.allow_auth('one-ip',str(number)))
        self.assertFalse(admission.allow_auth('one-ip','new-login'))
        self.assertTrue(admission.allow_auth('another-ip','new-login'))

    def test_errors_do_not_expose_internal_exception(self):
        server=load('security_server','server/server.py')
        left,right=socket.socketpair()
        right.sendall(struct.pack('!I',len(b'{"action":"heartbeat"}'))+b'{"action":"heartbeat"}')
        with patch.object(server,'handle_request',side_effect=RuntimeError('SECRET_DB_PATH')):
            server.handle_client(left,('127.0.0.1',1))
        try:
            response=right.recv(4096)
            self.assertNotIn(b'SECRET_DB_PATH',response)
            self.assertEqual(json.loads(response[4:])['code'],'internal_error')
        finally:right.close()

    def test_auth_limit_prevents_dispatch(self):
        server=load('limited_server','server/server.py')
        payload=json.dumps(dict(action='login',login='alice',password='test')).encode()
        left,right=socket.socketpair();right.sendall(struct.pack('!I',len(payload))+payload)
        with patch.object(server._admission,'allow_auth',return_value=False),patch.object(server,'handle_request') as dispatch:
            server.handle_client(left,('127.0.0.1',1))
            dispatch.assert_not_called()
        try:self.assertEqual(json.loads(right.recv(4096)[4:])['code'],'rate_limited')
        finally:right.close()

    def test_unicode_legacy_password_can_be_verified(self):
        server=load('password_server','server/server.py')
        self.assertTrue(server.verify_password('пароль','пароль'))
        self.assertFalse(server.verify_password('другой','пароль'))

    def test_concurrent_registration_returns_one_success(self):
        import tempfile
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        server=load('register_race','server/server.py')
        with tempfile.TemporaryDirectory() as folder:
            server.DB_FILE=str(Path(folder)/'users.db');server.init_db()
            with patch.object(server,'user_exists',return_value=False):
                with ThreadPoolExecutor(max_workers=2) as workers:
                    results=list(workers.map(lambda _:server.add_user('alice','test','Alice',''),range(2)))
            self.assertEqual(sorted(results),[False,True])
