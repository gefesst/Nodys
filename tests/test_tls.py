import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch
from test_foundation import ROOT
import sys
sys.path.insert(0,str(ROOT/'client'))
from transport.control import connect_api
from server_transport.tls import server_context

class TlsPolicyTests(unittest.TestCase):
    def test_remote_plaintext_is_rejected_before_connect(self):
        with patch('transport.control.load_config',return_value={'api_tls':False}), patch('socket.create_connection') as dial:
            with self.assertRaises(ValueError):
                with connect_api('example.com',5555): pass
            dial.assert_not_called()

    def test_public_server_requires_certificate(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):server_context('0.0.0.0')
            self.assertIsNone(server_context('127.0.0.1'))

class TlsHandshakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory()
        cls.cert=Path(cls.folder.name)/'certificate.pem'
        cls.key=Path(cls.folder.name)/'key.pem'
        from tls_fixture import create_certificate
        create_certificate(cls.cert,cls.key)
    @classmethod
    def tearDownClass(cls):cls.folder.cleanup()

    def exchange(self,host, trusted):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert,self.key)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(3)
        port=listener.getsockname()[1]
        errors=[]
        def serve():
            try:
                raw,_=listener.accept()
                with raw:
                    raw.settimeout(3)
                    try:
                        with context.wrap_socket(raw,server_side=True) as secure:
                            secure.sendall(secure.recv(4))
                    except ssl.SSLError:pass
                    except ConnectionResetError:
                        # Windows may reset the server socket after the client
                        # rejects its certificate. The caller still must raise
                        # SSLCertVerificationError; trusted exchanges must work.
                        if trusted and host == 'localhost':
                            raise
            except Exception as error:errors.append(error)
            finally:listener.close()
        worker=threading.Thread(target=serve);worker.start()
        config={'api_tls':True}
        if trusted:config['api_ca_file']=str(self.cert)
        try:
            with patch('transport.control.load_config',return_value=config):
                with connect_api(host,port) as secure:
                    secure.sendall(b'ping')
                    self.assertEqual(secure.recv(4),b'ping')
        finally:
            worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors,[])

    def test_trusted_matching_certificate(self):self.exchange('localhost',True)
    def test_untrusted_certificate_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):self.exchange('localhost',False)
    def test_wrong_hostname_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):self.exchange('127.0.0.1',True)
