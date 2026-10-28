"""Authenticated encrypted UDP relay. No plaintext compatibility path."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
import secrets
import socket
import sqlite3
import time
from cryptography.exceptions import InvalidTag
from shared.voice_protocol import DatagramCipher, HEADER, MAGIC, MAX_PACKET, PCM_BYTES
try:
    from .storage.database import connect as database_connection
    from .storage import voice_tickets
except ImportError:
    from storage.database import connect as database_connection
    from storage import voice_tickets

DB_FILE = os.environ.get('NODYS_DB_FILE') or str(Path(__file__).with_name('users.db'))
HOST = os.environ.get('NODYS_VOICE_HOST', '127.0.0.1')
PORT = int(os.environ.get('NODYS_VOICE_PORT', '5556'))


class VoiceRelay:
    """Single socket-loop owner; no concurrent mutation of crypto or routes."""
    def __init__(self, database):
        self.database = database
        self.process_id = secrets.token_hex(16)
        self.connections = {}
        self.last_cleanup = 0

    def _valid(self, connection, identity):
        ticket = voice_tickets.read(connection, identity)
        return ticket if ticket and voice_tickets.allowed(connection, ticket) else None

    def handle(self, sock, packet, address):
        if not HEADER.size + 16 < len(packet) <= MAX_PACKET or packet[:3] != MAGIC:
            return
        now = time.monotonic()
        if now-self.last_cleanup > 2:
            self.connections = {key: state for key,state in self.connections.items()
                                if now-state['seen'] < 20}
            self.last_cleanup = now
        identity = HEADER.unpack_from(packet)[1]
        try:
            with database_connection(self.database, timeout=0.2) as connection:
                ticket = self._valid(connection, identity)
                if not ticket:
                    self.connections.pop(identity, None)
                    return
                state = self.connections.get(identity)
                if state is None:
                    if ticket['claimed'] or len(self.connections) >= 1024:
                        return
                    cipher = DatagramCipher(identity, ticket['server_key'], ticket['client_key'])
                    sequence, payload = cipher.open(packet)
                    if payload != b'J' or not voice_tickets.claim(connection, identity, self.process_id):
                        return
                    # Commit claim before sending: a restart must not reset send nonces.
                    connection.commit()
                    state = dict(cipher=cipher, address=address, address_sequence=sequence,
                                 seen=now, ticket=ticket, rate_start=now, rate_count=0)
                    self.connections[identity] = state
                else:
                    sequence, payload = state['cipher'].open(packet)
                if payload not in (b'J', b'H', b'L') and not (payload[:1] == b'A' and len(payload) == PCM_BYTES+1):
                    return
                # Only a newer authenticated packet may move the NAT endpoint.
                if sequence >= state['address_sequence']:
                    state['address'] = address
                    state['address_sequence'] = sequence
                state['seen'] = now
                if now-state['rate_start'] >= 1:
                    state['rate_start'], state['rate_count'] = now, 0
                state['rate_count'] += 1
                if state['rate_count'] > 100:
                    return
                if payload in (b'J', b'H'):
                    sock.sendto(state['cipher'].seal(b'K'), state['address'])
                    return
                if payload == b'L':
                    if sequence == state['cipher'].highest:
                        self.connections.pop(identity, None)
                        connection.execute('DELETE FROM voice_tickets WHERE id=?', (identity,))
                    return
                sender_name = ticket['login'].encode('utf-8')
                if len(sender_name) > 255:
                    return
                output = b'R' + bytes([len(sender_name)]) + sender_name + payload[1:]
                for other_id, target in list(self.connections.items()):
                    other = target['ticket']
                    if other['login'] == ticket['login']:
                        continue
                    matches = (ticket['room'] and other['room'] == ticket['room']) or (
                        not ticket['room'] and not other['room'] and
                        ticket['peer'] == other['login'] and other['peer'] == ticket['login'])
                    if not matches or not self._valid(connection, other_id):
                        continue
                    try:
                        sock.sendto(target['cipher'].seal(output), target['address'])
                    except OSError:
                        pass
        except (ValueError, InvalidTag, sqlite3.Error, OSError):
            # Untrusted or revoked packets never alter routing or produce plaintext.
            return


def main():
    relay = VoiceRelay(DB_FILE)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((HOST, PORT))
        print(f'[VOICE] Encrypted UDP listening on {HOST}:{PORT}', flush=True)
        while True:
            packet, address = sock.recvfrom(MAX_PACKET+1)
            relay.handle(sock, packet, address)


if __name__ == '__main__':
    main()
