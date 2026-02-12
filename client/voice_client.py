import socket
import threading
import time
import queue
import numpy as np
import sounddevice as sd


class VoiceClient:
    def __init__(self, login, host="127.0.0.1", port=5556):
        self.login = login
        self.host = host
        self.port = port
        self.running = False
        self.sock = None
        self.sample_rate = 16000
        self.channels = 1
        self.dtype = "int16"
        self.frame_samples = 320
        self.play_q = queue.Queue(maxsize=50)
        self.recv_thread = None
        self.heartbeat_thread = None
        self.in_stream = None
        self.out_stream = None
        self.peer = None
        self.mic_enabled = True
        self.sound_enabled = True

        # speaking/activity metrics
        self._mic_level = 0.0
        self._peer_level = 0.0
        self._last_mic_voice_ts = 0.0
        self._last_peer_voice_ts = 0.0
        self._last_recv_ts = 0.0
        self._jitter_ms = 0.0
        self._avg_gap_ms = 20.0
        self._loss_score = 0.0
        self._latency_ms = 0.0
        self._ping_sent = {}
        self._voice_threshold = 0.015

        # quality metrics
        self._last_recv_ts = 0.0
        self._jitter_ms = 0.0
        self._avg_gap_ms = 20.0
        self._loss_score = 0.0
        self._latency_ms = 0.0
        self._ping_thread = None
        self._ping_seq = 0
        self._ping_sent = {}

    def start(self, peer_login):
        if self.running:
            return
        self.peer = peer_login
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.2)
        self._join()
        self._set_pair(self.login, self.peer, True)

        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()

        self.in_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=self.frame_samples,
            callback=self._capture_cb
        )
        self.out_stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=self.frame_samples,
            callback=self._play_cb
        )
        self.in_stream.start()
        self.out_stream.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        try:
            if self.peer:
                self._set_pair(self.login, self.peer, False)
        except Exception:
            pass

        for stream in (self.in_stream, self.out_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self.in_stream = None
        self.out_stream = None

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.peer = None
        self.mic_enabled = True
        self.sound_enabled = True
        self._mic_level = 0.0
        self._peer_level = 0.0
        self._last_mic_voice_ts = 0.0
        self._last_peer_voice_ts = 0.0
        self._last_recv_ts = 0.0
        self._jitter_ms = 0.0
        self._avg_gap_ms = 20.0
        self._loss_score = 0.0
        self._latency_ms = 0.0
        self._ping_sent = {}
        with self.play_q.mutex:
            self.play_q.queue.clear()

    def _join(self):
        msg = f"J|{self.login}".encode("utf-8")
        self.sock.sendto(msg, (self.host, self.port))

    def _set_pair(self, a, b, active):
        flag = "1" if active else "0"
        msg = f"S|{a}|{b}|{flag}".encode("utf-8")
        self.sock.sendto(msg, (self.host, self.port))

    def _heartbeat_loop(self):
        while self.running:
            try:
                self._join()
            except Exception:
                pass
            time.sleep(2)

    def _ping_loop(self):
        while self.running:
            try:
                seq = self._ping_seq
                self._ping_seq += 1
                payload = f"{seq}|{time.time():.6f}".encode("utf-8")
                self._ping_sent[seq] = time.time()
                self.sock.sendto(b"P|" + payload, (self.host, self.port))
                # cleanup old
                old = [k for k,v in self._ping_sent.items() if time.time()-v>5]
                for k in old:
                    self._ping_sent.pop(k, None)
            except Exception:
                pass
            time.sleep(2.0)

    def _capture_cb(self, indata, frames, time_info, status):
        if not self.running:
            return
        try:
            arr = indata.astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
            self._mic_level = rms
            if rms >= self._voice_threshold:
                self._last_mic_voice_ts = time.time()
        except Exception:
            pass

        if not self.mic_enabled:
            return
        try:
            pcm = indata.copy().tobytes()
            header = f"A|{self.login}|".encode("utf-8")
            self.sock.sendto(header + pcm, (self.host, self.port))
        except Exception:
            pass

    def _play_cb(self, outdata, frames, time_info, status):
        if not self.sound_enabled:
            outdata[:] = 0
            return
        try:
            chunk = self.play_q.get_nowait()
            arr = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)
            if len(arr) < len(outdata):
                outdata[:] = 0
                outdata[:len(arr)] = arr
            else:
                outdata[:] = arr[:len(outdata)]
        except queue.Empty:
            outdata[:] = 0
        except Exception:
            outdata[:] = 0

    def _recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(8192)
            except socket.timeout:
                continue
            except Exception:
                break

            if data.startswith(b"Q|"):
                try:
                    payload = data[2:].decode("utf-8", errors="ignore")
                    seq_s, _ts = payload.split("|", 1)
                    seq = int(seq_s)
                    sent = self._ping_sent.pop(seq, None)
                    if sent is not None:
                        self._latency_ms = max(0.0, (time.time() - sent) * 1000.0)
                except Exception:
                    pass
                continue

            if not data.startswith(b"R|"):
                continue
            sep = data.find(b"|", 2)
            if sep == -1:
                continue
            pcm = data[sep + 1:]
            now_ts = time.time()
            if self._last_recv_ts > 0:
                gap_ms = (now_ts - self._last_recv_ts) * 1000.0
                dev = abs(gap_ms - 20.0)
                self._avg_gap_ms = 0.95 * self._avg_gap_ms + 0.05 * gap_ms
                self._jitter_ms = 0.9 * self._jitter_ms + 0.1 * dev
                # rough loss proxy: big gaps
                miss = max(0.0, (gap_ms - 35.0) / 20.0)
                self._loss_score = min(100.0, 0.9 * self._loss_score + 10.0 * miss)
            self._last_recv_ts = now_ts

            try:
                arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
                self._peer_level = rms
                if rms >= self._voice_threshold:
                    self._last_peer_voice_ts = time.time()
            except Exception:
                pass
            try:
                self.play_q.put_nowait(pcm)
            except queue.Full:
                try:
                    _ = self.play_q.get_nowait()
                    self.play_q.put_nowait(pcm)
                except Exception:
                    pass

    def set_mic_enabled(self, enabled: bool):
        self.mic_enabled = bool(enabled)

    def set_sound_enabled(self, enabled: bool):
        self.sound_enabled = bool(enabled)

    def get_activity(self):
        now = time.time()
        me = (now - self._last_mic_voice_ts) < 0.35 if self.mic_enabled else False
        peer = (now - self._last_peer_voice_ts) < 0.35 if self.sound_enabled else False
        # quality bucket
        jitter = float(self._jitter_ms)
        latency = float(self._latency_ms)
        loss = float(self._loss_score)
        score = 100.0 - (jitter * 1.5 + max(0.0, latency - 60.0) * 0.6 + loss * 0.8)
        if score >= 75:
            quality = "Отличное"
        elif score >= 50:
            quality = "Хорошее"
        elif score >= 30:
            quality = "Среднее"
        else:
            quality = "Плохое"

        return {
            "mic_level": self._mic_level,
            "peer_level": self._peer_level,
            "me_speaking": me,
            "peer_speaking": peer,
            "latency_ms": round(latency, 1),
            "jitter_ms": round(jitter, 1),
            "quality": quality,
            "quality_score": round(max(0.0, min(100.0, score)), 1),
        }
