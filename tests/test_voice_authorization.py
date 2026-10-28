import tempfile
from pathlib import Path
import unittest
from test_foundation import load

class Sink:
    def __init__(self): self.packets = []
    def sendto(self, data, addr): self.packets.append((data, addr))

class VoiceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.server = load('tcp_test', 'server/server.py')
        self.voice = load('udp_test', 'server/voice_server.py')
        self.server.DB_FILE = self.voice.DB_FILE = str(Path(self.folder.name)/'users.db')
        self.server.CHAT_DB = str(Path(self.folder.name)/'chat.db')
        self.server.init_db(); self.server.init_chat_db()
        self.tokens = {}
        self.addresses = {'alice':('127.0.0.1',10001),'bob':('127.0.0.1',10002)}
        for login in self.addresses:
            self.server.add_user(login,'synthetic',login,'')
            self.tokens[login] = self.server.create_session(login)[0]
        self.channel = self.server.create_channel('alice','test')
        self.server.join_channel_by_code('bob',self.channel['code'])
        self.sink = Sink()
        for login in self.addresses:
            room = str(self.channel['id']) if login == 'alice' else f"channel:{self.channel['id']}"
            self.packet(login, f'C|{login}|{self.tokens[login]}|{room}'.encode())

    def packet(self, login, data): self.voice.handle_packet(self.sink,data,self.addresses[login])
    def audio(self, login):
        self.sink.packets.clear()
        self.packet(login, f'A|{login}|'.encode()+b'\0\0')
        return len(self.sink.packets)

    def test_authorized_audio_and_room_canonicalization(self):
        self.assertEqual(self.audio('alice'),1)
        self.assertEqual(self.audio('bob'),1)

    def test_kick_revokes_sender_and_recipient(self):
        self.server.remove_channel_member('alice',self.channel['id'],'bob')
        self.assertEqual(self.audio('bob'),0)
        self.assertEqual(self.audio('alice'),0)

    def test_logout_revokes_sender_and_recipient(self):
        self.server.delete_session(self.tokens['bob'])
        self.assertEqual(self.audio('bob'),0)
        self.assertEqual(self.audio('alice'),0)

    def test_policy_change_revokes_member(self):
        self.server.update_channel_settings('alice',self.channel['id'],'test','',voice_min_role='admin')
        self.assertEqual(self.audio('alice'),0)
        self.assertEqual(self.audio('bob'),0)

    def test_deleted_channel_stops_audio(self):
        self.server.delete_channel('alice',self.channel['id'])
        self.assertEqual(self.audio('bob'),0)

    def test_invalid_and_expired_session(self):
        for expiry in ('invalid','2000-01-01T00:00:00+00:00'):
            with self.server.database_connection(self.server.DB_FILE) as conn:
                conn.execute('UPDATE sessions SET expires_at=? WHERE token=?',(expiry,self.tokens['bob']))
            self.assertFalse(self.voice.validate_token('bob',self.tokens['bob']))
            self.assertEqual(self.audio('alice'),0)

    def test_ended_private_call_stops_audio(self):
        self.server.send_friend_request('alice','bob'); self.server.accept_friend_request('alice','bob')
        self.server.start_call('alice','bob'); self.server.accept_call('bob','alice')
        for login in self.addresses:
            self.packet(login,f'L|{login}|channel:{self.channel["id"]}'.encode())
        self.packet('alice',f'S|alice|{self.tokens["alice"]}|alice|bob|1'.encode())
        self.assertEqual(self.audio('alice'),1)
        self.server.end_call('alice','bob')
        self.assertEqual(self.audio('alice'),0)
        self.assertEqual(self.audio('bob'),0)
