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

    def test_mutations_of_every_packet_byte_are_rejected_without_consuming_sequence(self):
        packet=self.client.seal(b'payload')
        for index in range(len(packet)):
            damaged=bytearray(packet);damaged[index]^=1
            with self.assertRaises((ValueError,InvalidTag)):
                self.server.open(bytes(damaged))
        self.assertEqual(self.server.open(packet)[1],b'payload')

    def test_concurrent_send_counters_are_unique(self):
        from concurrent.futures import ThreadPoolExecutor
        from shared.voice_protocol import HEADER
        with ThreadPoolExecutor(max_workers=8) as pool:
            packets=list(pool.map(lambda _:self.client.seal(b'payload'),range(100)))
        self.assertEqual({HEADER.unpack_from(packet)[2] for packet in packets},set(range(100)))

    def test_malformed_lengths_and_identity_do_not_mutate_receiver(self):
        import random
        rng=random.Random(123)
        for size in range(0,1250,7):
            with self.assertRaises((ValueError,InvalidTag)):
                self.server.open(rng.randbytes(size))
        self.assertEqual(self.server.highest,-1)
