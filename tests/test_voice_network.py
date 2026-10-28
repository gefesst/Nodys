"""Real TLS control + UDP relay, with synthetic PCM and no audio hardware."""
from pathlib import Path
import socket
import ssl
import threading
import time
import unittest
from unittest.mock import patch
import test_voice_authorization as fixtures
from tls_fixture import create_certificate
import sys
from test_foundation import ROOT
sys.path.insert(0, str(ROOT / "client"))
from transport.voice import SecureVoiceTransport
from voice_client import VoiceClient


class VoiceNetworkTests(fixtures.VoiceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        cert,key=Path(self.folder.name)/'cert.pem',Path(self.folder.name)/'key.pem'
        create_certificate(cert,key)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        self.stop=threading.Event()
        self.old_relays=[]
        tcp=socket.socket();tcp.bind(('127.0.0.1',0));tcp.listen();tcp.settimeout(.1)
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.settimeout(.1)
        self.port=udp.getsockname()[1]
        self.wire=[]
        def control():
            while not self.stop.is_set():
                try: conn,addr=tcp.accept()
                except socket.timeout:continue
                self.server.handle_client(conn,addr,context)
        def relay():
            while not self.stop.is_set():
                try: packet,addr=udp.recvfrom(1201)
                except socket.timeout:continue
                self.wire.append(packet)
                self.relay.handle(udp,packet,addr)
        workers=[threading.Thread(target=control),threading.Thread(target=relay)]
        for worker in workers:worker.start()
        def cleanup():
            self.stop.set()
            for worker in workers: worker.join(5)
            tcp.close();udp.close()
            self.relay.close()
            for old in self.old_relays: old.close()
            self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.addCleanup(cleanup)
        self.enterContext(patch('transport.voice.get_api_endpoint',return_value=('localhost',tcp.getsockname()[1])))
        self.enterContext(patch('transport.control.load_config',return_value={'api_tls':True,'api_ca_file':str(cert)}))

    def transport(self, login):
        result=SecureVoiceTransport(login,self.tokens[login],'127.0.0.1',self.port,room=self.channel['id'])
        result.socket.settimeout(.2)
        self.addCleanup(result.close)
        return result

    def test_encrypted_roundtrip_and_revocation(self):
        alice,bob=self.transport('alice'),self.transport('bob')
        pcm=b'\x21\x03'*320
        alice.send(b'A'+pcm)
        received=bob.receive()
        self.assertEqual(received[:7],b'R\x05alice')
        self.assertEqual(received[-640:],pcm)
        self.assertTrue(all(p.startswith(b'NV2') and pcm not in p and self.tokens['alice'].encode() not in p for p in self.wire))
        self.server.remove_channel_member('alice',self.channel['id'],'bob')
        alice.send(b'A'+pcm)
        with self.assertRaises(socket.timeout):bob.receive()

    def test_device_failure_closes_network_and_partial_stream(self):
        client=VoiceClient('alice',self.tokens['alice'],'127.0.0.1',self.port)
        from unittest.mock import Mock
        partial=Mock()
        with patch('voice_client.sd.InputStream',return_value=partial), patch('voice_client.sd.OutputStream',side_effect=RuntimeError('no output device')):
            with self.assertRaises(RuntimeError):client.start(room_id=self.channel['id'])
        self.assertFalse(client.running)
        self.assertIsNone(client.transport)
        self.assertFalse(client.recv_thread.is_alive())
        partial.close.assert_called_once()

    def test_client_renews_keys_and_stops_reconnect_worker(self):
        client=VoiceClient('alice',self.tokens['alice'],'127.0.0.1',self.port)
        self.addCleanup(client.stop)
        with patch.object(client,'_start_audio'):
            client.start(room_id=self.channel['id'])
        first=client.transport
        first.expires=0
        deadline=time.monotonic()+5
        while client.transport in (None,first) and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertIsNotNone(client.transport)
        self.assertNotEqual(client.transport.cipher.transport_id,first.cipher.transport_id)
        client.stop()
        self.assertFalse(client.recv_thread.is_alive())

    def test_udp_restart_automatically_gets_new_keys(self):
        client=VoiceClient('alice',self.tokens['alice'],'127.0.0.1',self.port)
        client.ACK_TIMEOUT=.3
        self.addCleanup(client.stop)
        with patch.object(client,'_start_audio'):
            client.start(room_id=self.channel['id'])
        identity=client.transport.cipher.transport_id
        old_relay=self.relay
        self.relay=self.voice.VoiceRelay(self.server.DB_FILE)
        self.old_relays.append(old_relay)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if client.transport and client.transport.cipher.transport_id != identity:
                break
            time.sleep(.05)
        self.assertIsNotNone(client.transport)
        self.assertNotEqual(client.transport.cipher.transport_id,identity)
