"""Synthetic relay capacity probe; no audio hardware or external network claims."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import server
from server.voice_server import VoiceRelay
from shared.voice_protocol import DatagramCipher, audio_frame


class Sink:
    def __init__(self):
        self.count = 0
    def sendto(self, packet, address):
        self.count += 1


def benchmark(peers, frames):
    with tempfile.TemporaryDirectory(prefix='nodys-bench-') as folder:
        server.DB_FILE = str(Path(folder)/'users.db')
        server.CHAT_DB = str(Path(folder)/'chat.db')
        server.init_db(); server.init_chat_db()
        channel = None
        ciphers = []
        sink = Sink()
        relay = VoiceRelay(server.DB_FILE)
        try:
            for index in range(peers):
                login = f'peer{index}'
                server.add_user(login, 'synthetic-benchmark-only', login, '')
                token = server.create_session(login)[0]
                if channel is None:
                    channel = server.create_channel(login, 'benchmark')
                else:
                    server.join_channel_by_code(login, channel['code'])
                grant = server.handle_request(dict(action='voice_ticket', token=token, room=channel['id']))
                cipher = DatagramCipher(bytes.fromhex(grant['id']), bytes.fromhex(grant['client_key']), bytes.fromhex(grant['server_key']))
                ciphers.append(cipher)
                relay.handle(sink, cipher.seal(b'J'), ('127.0.0.1', 20000+index))
            sink.count = 0
            samples = []
            started = time.perf_counter()
            for sequence in range(frames):
                for index, cipher in enumerate(ciphers):
                    packet = cipher.seal(audio_frame(sequence, b'\0'*640))
                    tick = time.perf_counter()
                    relay.handle(sink, packet, ('127.0.0.1', 20000+index))
                    samples.append((time.perf_counter()-tick)*1000)
            elapsed = time.perf_counter()-started
            expected = peers*frames*(peers-1)
            if sink.count != expected:
                raise RuntimeError(f'Unexpected delivery count: {sink.count} != {expected}')
            return dict(peers=peers, incoming_packets=peers*frames, forwarded_packets=sink.count,
                        elapsed_seconds=round(elapsed,3), incoming_per_second=round(peers*frames/elapsed),
                        required_incoming_per_second=peers*50,
                        packet_p50_ms=round(statistics.median(samples),3),
                        packet_p95_ms=round(sorted(samples)[int(len(samples)*.95)],3))
        finally:
            relay.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--peers', type=int, default=8, choices=range(2,33))
    parser.add_argument('--frames', type=int, default=50, choices=range(1,81))
    args = parser.parse_args()
    print(json.dumps(benchmark(args.peers, args.frames), indent=2))
