"""Nodys v1 authenticated datagrams; keys are issued over verified TLS.

Separate directional keys, monotonic 64-bit nonces, authenticated headers and a
128-packet replay window. A cipher instance must never be recreated with keys
that have already sent packets. Server claims enforce this across restarts.
"""
import struct
import threading
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'NV1'
HEADER = struct.Struct('!3s16sQ')
MAX_PACKET = 1200
PCM_BYTES = 640


class DatagramCipher:
    def __init__(self, transport_id, send_key, receive_key):
        if len(transport_id) != 16 or len(send_key) != 32 or len(receive_key) != 32:
            raise ValueError('Invalid voice key material')
        self.transport_id = transport_id
        self.sender = AESGCM(send_key)
        self.receiver = AESGCM(receive_key)
        self.sequence = 0
        self.highest = -1
        self.seen = 0
        self.lock = threading.Lock()

    def seal(self, payload):
        if not payload or len(payload) > MAX_PACKET - HEADER.size - 16:
            raise ValueError('Invalid voice payload length')
        with self.lock:
            if self.sequence >= 2**64:
                raise ValueError('Voice key exhausted')
            sequence = self.sequence
            self.sequence += 1
            header = HEADER.pack(MAGIC, self.transport_id, sequence)
            return header + self.sender.encrypt(struct.pack('!IQ', 0, sequence), payload, header)

    def open(self, packet):
        if not HEADER.size + 16 < len(packet) <= MAX_PACKET:
            raise ValueError('Invalid datagram length')
        magic, identity, sequence = HEADER.unpack_from(packet)
        if magic != MAGIC or identity != self.transport_id:
            raise ValueError('Invalid datagram identity')
        with self.lock:
            offset = self.highest - sequence
            if offset >= 128 or (offset >= 0 and self.seen & (1 << offset)):
                raise ValueError('Replayed datagram')
            # Authenticate before changing the replay window.
            payload = self.receiver.decrypt(struct.pack('!IQ', 0, sequence),
                                            packet[HEADER.size:], packet[:HEADER.size])
            if sequence > self.highest:
                shift = sequence - self.highest
                self.seen = ((self.seen << min(shift, 128)) | 1) & ((1 << 128) - 1)
                self.highest = sequence
            else:
                self.seen |= 1 << offset
            return sequence, payload
