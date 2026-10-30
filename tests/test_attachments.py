import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
import base64
import hashlib
import unittest
import uuid
from unittest.mock import patch
import test_voice_authorization as fixtures
from shared.attachments import CHUNK_SIZE


class AttachmentTests(fixtures.VoiceFixture, unittest.TestCase):
    def request(self, who, action, **data):
        return self.server.handle_request(dict(action=action, token=self.tokens[who], **data))

    def upload(self, data=b'hello\x00image bytes', **scope):
        aid = uuid.uuid4().hex
        result = self.request('alice', 'begin_attachment', attachment_id=aid,
                              filename='пример.png', file_size=len(data),
                              sha256=hashlib.sha256(data).hexdigest(), **scope)
        self.assertEqual(result['status'], 'ok', result)
        for offset in range(0, len(data), CHUNK_SIZE):
            result = self.request('alice', 'upload_attachment_chunk', attachment_id=aid,
                                  offset=offset, chunk=base64.b64encode(data[offset:offset+CHUNK_SIZE]).decode())
            self.assertEqual(result['status'], 'ok', result)
        return aid

    def test_private_binary_roundtrip_and_history_after_restart(self):
        self.server.send_friend_request('alice', 'bob')
        self.server.accept_friend_request('alice', 'bob')
        data = bytes(range(256)) * 220
        aid = self.upload(data, to_user='bob')
        self.assertEqual(self.request('bob', 'download_attachment_chunk', attachment_id=aid)['status'], 'error')
        result = self.request('alice', 'send_message', to_user='bob', text='', attachment_id=aid, client_message_id='file-send')
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(self.request('alice', 'send_message', to_user='bob', text='', attachment_id=aid, client_message_id='file-send'), result)
        self.server.init_chat_db()
        rows = self.request('bob', 'get_messages', to_user='alice', paged=True)['messages']
        self.assertEqual(rows[0]['attachment']['name'], 'пример.png')
        received = bytearray()
        while len(received) < len(data):
            response = self.request('bob', 'download_attachment_chunk', attachment_id=aid, offset=len(received))
            self.assertEqual(response['status'], 'ok', response)
            received.extend(base64.b64decode(response['chunk']))
        self.assertEqual(bytes(received), data)
        summary = self.request('bob', 'get_unread_counts')['summaries']['alice']
        self.assertIn('пример.png', summary['text'])

    def test_channel_membership_and_binding(self):
        aid = self.upload(channel_id=self.channel['id'], room_id=0)
        self.assertEqual(self.request('bob', 'send_channel_message', channel_id=self.channel['id'], text='', attachment_id=aid)['status'], 'error')
        result = self.request('alice', 'send_channel_message', channel_id=self.channel['id'], text='image', attachment_id=aid)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(self.request('bob', 'download_attachment_chunk', attachment_id=aid)['status'], 'ok')
        self.request('bob', 'leave_channel', channel_id=self.channel['id'])
        self.assertEqual(self.request('bob', 'download_attachment_chunk', attachment_id=aid)['status'], 'error')

    def test_incomplete_hash_mismatch_and_chunk_replay(self):
        aid = uuid.uuid4().hex
        self.assertEqual(self.request('alice', 'begin_attachment', attachment_id=aid, filename='x.bin',
            file_size=4, sha256=hashlib.sha256(b'abcd').hexdigest(), channel_id=self.channel['id'])['status'], 'ok')
        payload = dict(attachment_id=aid, offset=0, chunk=base64.b64encode(b'ab').decode())
        self.assertEqual(self.request('alice', 'upload_attachment_chunk', **payload)['status'], 'ok')
        self.assertEqual(self.request('alice', 'upload_attachment_chunk', **payload)['status'], 'ok')
        self.assertEqual(self.request('alice', 'send_channel_message', channel_id=self.channel['id'], text='', attachment_id=aid)['status'], 'error')
        self.assertEqual(self.request('alice', 'upload_attachment_chunk', attachment_id=aid, offset=2, chunk=base64.b64encode(b'XX').decode())['status'], 'ok')
        self.assertEqual(self.request('alice', 'send_channel_message', channel_id=self.channel['id'], text='', attachment_id=aid)['status'], 'error')

    def test_limits_unsafe_names_and_unauthorized_guesses(self):
        for filename, size in (('../outside', 10), ('C:\\evil', 10), ('fine', 10485761)):
            result = self.request('alice', 'begin_attachment', attachment_id=uuid.uuid4().hex,
                filename=filename, file_size=size, sha256='0'*64, channel_id=self.channel['id'])
            self.assertEqual(result['status'], 'error')
        aid = self.upload(channel_id=self.channel['id'])
        self.server.add_user('other', 'synthetic', 'Other', '')
        self.tokens['other'] = self.server.create_session('other')[0]
        self.assertEqual(self.request('other', 'download_attachment_chunk', attachment_id=aid)['status'], 'error')
        self.assertEqual(self.request('other', 'upload_attachment_chunk', attachment_id=aid, offset=0, chunk='YQ==')['status'], 'error')
        with patch('storage.attachments.USER_QUOTA', 1):
            result = self.request('alice', 'begin_attachment', attachment_id=uuid.uuid4().hex, filename='x',
                file_size=2, sha256='0'*64, channel_id=self.channel['id'])
            self.assertEqual(result['status'], 'error')


class AttachmentTransportTests(fixtures.VoiceFixture, unittest.TestCase):
    def test_background_transfer_over_tcp_is_byte_exact_and_atomic(self):
        import os
        import socket
        import threading
        import time
        from pathlib import Path
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from application.attachment_transfer import AttachmentTransfer
        app = QApplication.instance() or QApplication([])
        self.server.send_friend_request('alice', 'bob')
        self.server.accept_friend_request('alice', 'bob')
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(.1)
        stop = threading.Event()
        def serve():
            while not stop.is_set():
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self.server.handle_client(conn, addr)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        self.addCleanup(listener.close)
        self.addCleanup(stop.set)
        source = Path(self.folder.name)/'source.bin'
        target = Path(self.folder.name)/'download.bin'
        data = os.urandom(160000)
        source.write_bytes(data)
        target.write_bytes(b'preserve until verified')
        ticks = []
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        self.addCleanup(timer.stop)
        def run(transfer):
            done = []
            transfer.finished.connect(done.append)
            transfer.start()
            deadline = time.monotonic()+10
            while not done and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            self.assertTrue(done, 'transfer timed out')
            self.assertEqual(done[0]['status'], 'ok', done)
            return done[0]
        with patch('settings.get_api_endpoint', return_value=listener.getsockname()):
            result = run(AttachmentTransfer(self.tokens['alice'], {'to_user':'bob'}, source))
            metadata = result['attachment']
            result = self.server.handle_request(dict(action='send_message', token=self.tokens['alice'], to_user='bob', text='', attachment_id=metadata['id']))
            self.assertEqual(result['status'], 'ok', result)
            run(AttachmentTransfer(self.tokens['bob'], {}, target, metadata))
            from PySide6.QtGui import QImage, QColor
            picture = Path(self.folder.name)/'picture.png'
            image = QImage(640, 360, QImage.Format_RGB32)
            image.fill(QColor('#89AAFF'))
            self.assertTrue(image.save(str(picture)))
            meta = run(AttachmentTransfer(self.tokens['alice'], {'to_user':'bob'}, picture))['attachment']
            sent = self.server.handle_request(dict(action='send_message', token=self.tokens['alice'], to_user='bob', text='', attachment_id=meta['id']))
            self.assertEqual(sent['status'], 'ok', sent)
            preview = run(AttachmentTransfer(self.tokens['bob'], {}, None, meta, preview=True))
            self.assertEqual(preview['image'].size(), image.size())
            self.assertEqual(preview['image'].pixelColor(0, 0), image.pixelColor(0, 0))

        self.assertEqual(target.read_bytes(), data)
        self.assertTrue(ticks, 'GUI event loop should remain responsive')
        self.assertFalse(list(target.parent.glob('.noda-download-*')))
