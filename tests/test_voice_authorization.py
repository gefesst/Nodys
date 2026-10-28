import tempfile
from pathlib import Path
import unittest
from test_foundation import load
from shared.voice_protocol import DatagramCipher, audio_frame

class Sink:
    def __init__(self): self.packets = []
    def sendto(self, data, addr): self.packets.append((data, addr))

class VoiceFixture:
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
        self.relay = self.voice.VoiceRelay(self.server.DB_FILE)
        self.ciphers = {}
        self.audio_sequence = {}
        self.addCleanup(self.relay.close)
        for login in self.addresses:
            self.connect(login, room=str(self.channel['id']))

    def connect(self, login, room=None, peer=None):
        result = self.server.handle_request(dict(action='voice_ticket', login=login,
                    token=self.tokens[login], room=room, peer=peer))
        self.assertEqual(result['status'], 'ok', result)
        self.ciphers[login] = DatagramCipher(bytes.fromhex(result['id']),
                bytes.fromhex(result['client_key']), bytes.fromhex(result['server_key']))
        self.packet(login, b'J')

    def packet(self, login, data):
        if data[:1] == b'A':
            seq = self.audio_sequence.get(login,0)
            self.audio_sequence[login] = seq + 1
            data = audio_frame(seq, data[1:])
        packet = self.ciphers[login].seal(data)
        self.relay.handle(self.sink, packet, self.addresses[login])
        return packet

    def audio(self, login):
        self.sink.packets.clear()
        self.packet(login, b'A'+b'\0'*640)
        return len(self.sink.packets)


class VoiceAuthorizationTests(VoiceFixture, unittest.TestCase):
    def test_authorized_audio_and_room_canonicalization(self):
        self.assertEqual(self.audio('alice'),1)
        payload = self.ciphers['bob'].open(self.sink.packets[0][0])[1]
        self.assertEqual(payload[:7], b'R\x05alice')
        self.assertEqual(payload[-640:], b'\0'*640)
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
            self.assertEqual(self.audio('alice'),0)
            self.assertEqual(self.audio('bob'),0)

    def test_ended_private_call_stops_audio(self):
        self.server.send_friend_request('alice','bob'); self.server.accept_friend_request('alice','bob')
        self.server.start_call('alice','bob'); self.server.accept_call('bob','alice')
        for login in self.addresses:
            self.connect(login, peer='bob' if login == 'alice' else 'alice')
        self.assertEqual(self.audio('alice'),1)
        self.server.end_call('alice','bob')
        self.assertEqual(self.audio('alice'),0)
        self.assertEqual(self.audio('bob'),0)

    def test_restart_cannot_reuse_claimed_keys(self):
        self.relay.close()
        self.relay = self.voice.VoiceRelay(self.server.DB_FILE)
        self.addCleanup(self.relay.close)
        self.sink.packets.clear()
        self.packet('alice',b'J')
        self.assertEqual(self.sink.packets,[])
        for login in self.addresses: self.connect(login,room=self.channel['id'])
        self.assertEqual(self.audio('alice'),1)

    def test_plaintext_and_tampered_packets_are_silent(self):
        self.sink.packets.clear()
        self.relay.handle(self.sink,b'J|alice|'+self.tokens['alice'].encode(),self.addresses['alice'])
        packet=self.ciphers['alice'].seal(audio_frame(999,b'\0'*640))
        self.relay.handle(self.sink,packet[:-1]+bytes([packet[-1]^1]),self.addresses['alice'])
        self.assertEqual(self.sink.packets,[])
        self.relay.handle(self.sink,packet,self.addresses['alice'])
        self.assertEqual(len(self.sink.packets),1)
        self.relay.handle(self.sink,packet,self.addresses['alice'])
        self.assertEqual(len(self.sink.packets),1)

    def test_rebinding_requires_authenticated_new_packet(self):
        stale=self.ciphers['alice'].seal(b'H')
        self.addresses['alice']=('127.0.0.1',10003)
        self.packet('alice',b'H')
        self.relay.handle(self.sink,stale,('127.0.0.1',10001))
        identity=self.ciphers['alice'].transport_id
        self.assertEqual(self.relay.connections[identity]['address'],self.addresses['alice'])

    def test_new_ticket_revokes_old_key(self):
        old=self.ciphers['alice']
        self.connect('alice',room=self.channel['id'])
        self.sink.packets.clear()
        self.relay.handle(self.sink,old.seal(audio_frame(999,b'\0'*640)),self.addresses['alice'])
        self.assertEqual(self.sink.packets,[])
        self.assertEqual(self.audio('alice'),1)

    def test_ticket_denies_wrong_scope_and_identity(self):
        for extra in ({'peer':'bob'},{'room':'invalid'},{'room':self.channel['id'],'peer':'bob'},
                      {'room':self.channel['id'],'token':'invalid'}):
            request=dict(action='voice_ticket',login='alice',token=self.tokens['alice'])
            request.update(extra)
            self.assertEqual(self.server.handle_request(request)['status'],'error')

    def test_expired_ticket_and_other_room_do_not_receive(self):
        other=self.server.create_channel('bob','separate')
        self.connect('bob',room=other['id'])
        self.assertEqual(self.audio('alice'),0)
        self.connect('bob',room=self.channel['id'])
        with self.server.database_connection(self.server.DB_FILE) as connection:
            connection.execute('UPDATE voice_tickets SET expires=0 WHERE login=?',('bob',))
        self.assertEqual(self.audio('alice'),0)
        self.assertEqual(self.audio('bob'),0)
