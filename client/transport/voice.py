"""Voice credentials over the control channel; only encrypted bytes over UDP."""
import json
import socket
import struct
import time
from cryptography.exceptions import InvalidTag
from shared.voice_protocol import DatagramCipher, MAX_PACKET
from transport.control import connect_api
from settings import get_api_endpoint


def _exact(connection, count):
    data = b''
    while len(data) < count:
        part = connection.recv(count-len(data))
        if not part:
            raise ConnectionError('Сервер закрыл соединение')
        data += part
    return data


def request_ticket(login, token, room, peer):
    payload = json.dumps(dict(action='voice_ticket',login=login,token=token,room=room,peer=peer)).encode()
    with connect_api(*get_api_endpoint()) as connection:
        connection.sendall(struct.pack('!I', len(payload))+payload)
        length = struct.unpack('!I', _exact(connection, 4))[0]
        if not 0 < length <= 4096:
            raise ValueError('Некорректный ответ голосового сервера')
        response = json.loads(_exact(connection, length))
    if response.get('status') != 'ok':
        raise ValueError(response.get('message', 'Голосовое соединение недоступно'))
    return response


class SecureVoiceTransport:
    def __init__(self, login, token, host, port, room=None, peer=None):
        ticket = request_ticket(login, token, room, peer)
        self.cipher = DatagramCipher(bytes.fromhex(ticket['id']), bytes.fromhex(ticket['client_key']),
                                     bytes.fromhex(ticket['server_key']))
        self.expires = ticket['expires']
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.connect((host, port))
            self.socket.settimeout(0.2)
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                self.send(b'J')
                try:
                    if self.receive() == b'K':
                        self.socket.settimeout(0.01)
                        return
                except (socket.timeout, ConnectionRefusedError):
                    continue
            raise TimeoutError('Голосовой сервер не подтвердил защищённое соединение')
        except BaseException:
            self.socket.close()
            raise

    def send(self, payload):
        self.socket.send(self.cipher.seal(payload))

    def receive(self):
        packet = self.socket.recv(MAX_PACKET+1)
        try:
            return self.cipher.open(packet)[1]
        except (ValueError, InvalidTag):
            return b''

    def close(self):
        try:
            self.send(b'L')
        except (OSError, ValueError):
            pass
        self.socket.close()
