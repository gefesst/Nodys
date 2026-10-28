import secrets
import unittest
from cryptography.exceptions import InvalidTag
from shared.voice_protocol import DatagramCipher

class CryptoTests(unittest.TestCase):
    def setUp(self):
        identity=secrets.token_bytes(16)
        a,b=secrets.token_bytes(32),secrets.token_bytes(32)
        self.client=DatagramCipher(identity,a,b)
        self.server=DatagramCipher(identity,b,a)

    def test_reordering_and_replay_window(self):
        packets=[self.client.seal(b'PCM') for _ in range(150)]
        self.server.open(packets[149])
        self.server.open(packets[148])
        with self.assertRaises(ValueError): self.server.open(packets[148])
        with self.assertRaises(ValueError): self.server.open(packets[0])

    def test_tampering_does_not_advance_window(self):
        packet=self.client.seal(b'audio')
        altered=bytearray(packet);altered[26]^=128
        with self.assertRaises(InvalidTag): self.server.open(bytes(altered))
        self.assertEqual(self.server.open(packet)[1],b'audio')

    def test_direction_is_not_reflectable(self):
        packet=self.client.seal(b'PCM')
        with self.assertRaises(InvalidTag): self.client.open(packet)
        self.assertNotIn(b'PCM',packet)

    def test_counter_exhaustion(self):
        self.client.sequence=2**64
        with self.assertRaises(ValueError):self.client.seal(b'x')
