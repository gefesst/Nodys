from transport.voice import SecureVoiceTransport
import socket
import queue
import threading
import time
from audio.mixer import PcmMixer
import numpy as np
import sounddevice as sd


class VoiceClient:
    ACK_TIMEOUT = 8
    def __init__(self, login, token: str = "", host="127.0.0.1", port=5556):
        self.login = login
        self.token = token or ""
        self.host = host
        self.port = port
        self.running = False
        self.transport = None
        self._stop_event = threading.Event()
        self.sample_rate = 16000
        self.channels = 1
        self.dtype = "int16"
        self.frame_samples = 320
        # Короткий джиттер-буфер для сглаживания неровной UDP-доставки.
        self.mixer = PcmMixer(frame_samples=self.frame_samples)
        self._outgoing = queue.Queue(maxsize=8)
        self._speaker_arrivals = {}
        self.recv_thread = None
        self.in_stream = None
        self.out_stream = None
        self.peer = None
        self.room_id = None
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
        self._voice_threshold = 0.015

    def start(self, peer_login=None, room_id=None, cancel_event=None):
        if self.running:
            return
        if self.recv_thread and self.recv_thread.is_alive():
            raise RuntimeError("Предыдущее голосовое соединение ещё закрывается")
        self.peer = peer_login or None
        self.room_id = str(room_id) if room_id is not None else None

        if not self.peer and not self.room_id:
            raise ValueError("peer_login or room_id is required")

        self._outgoing = queue.Queue(maxsize=8)
        self._stop_event.clear()
        self.transport = SecureVoiceTransport(self.login, self.token, self.host, self.port,
                                              self.room_id, self.peer)
        if cancel_event is not None and cancel_event.is_set():
            self.transport.close()
            self.transport = None
            return
        self.running = True
        self._reset_runtime_metrics()
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        try:
            self._start_audio()
        except BaseException:
            self.stop()
            raise

    def _start_audio(self):
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
        self._stop_event.set()
        for stream in (self.in_stream, self.out_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self.in_stream = None
        self.out_stream = None

        if self.transport:
            self.transport.close()
        if self.recv_thread and self.recv_thread is not threading.current_thread():
            self.recv_thread.join(timeout=7)
        self.transport = None
        self.peer = None
        self.room_id = None
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
        self.mixer.clear()
        self._speaker_arrivals.clear()

    def _reset_runtime_metrics(self):
        self._mic_level = 0.0
        self._peer_level = 0.0
        self._last_mic_voice_ts = 0.0
        self._last_peer_voice_ts = 0.0
        self._last_recv_ts = 0.0
        self._jitter_ms = 0.0
        self._avg_gap_ms = 20.0
        self._loss_score = 0.0
        self._latency_ms = 0.0
        self.mixer.clear()
        self._speaker_arrivals.clear()

    def _capture_cb(self, indata, frames, time_info, status):
        if not self.running:
            return
        try:
            arr = indata.astype(np.float32) / 32768.0
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
            try:
                self._outgoing.put_nowait(pcm)
            except queue.Full:
                try:
                    self._outgoing.get_nowait()
                except queue.Empty:
                    pass
                self._outgoing.put_nowait(pcm)
        except Exception:
            pass

    def _play_cb(self, outdata, frames, time_info, status):
        chunk = self.mixer.mix()
        outdata[:] = 0
        if self.sound_enabled:
            count = min(len(outdata), len(chunk))
            outdata[:count, 0] = chunk[:count]

    def _recv_loop(self):
        try:
            self._run_network()
        finally:
            transport = self.transport
            if transport:
                transport.close()
            self.transport = None

    def _run_network(self):
        last_ack = time.monotonic()
        last_ping = 0
        while not self._stop_event.is_set():
            transport = self.transport
            now = time.monotonic()
            if transport is None or now-last_ack > self.ACK_TIMEOUT or time.time() > transport.expires-60:
                if transport:
                    transport.close()
                self.transport = None
                self.mixer.clear()
                try:
                    replacement = SecureVoiceTransport(self.login, self.token, self.host, self.port,
                                                       self.room_id, self.peer)
                    if self._stop_event.is_set():
                        replacement.close()
                        return
                    self._outgoing = queue.Queue(maxsize=8)
                    self.transport = replacement
                    last_ack = time.monotonic()
                    last_ping = 0
                except Exception:
                    self._stop_event.wait(2)
                continue
            try:
                if now-last_ping >= 2:
                    transport.send(b'H')
                    last_ping = now
                for _ in range(8):
                    try:
                        pcm = self._outgoing.get_nowait()
                    except queue.Empty:
                        break
                    transport.send(b'A' + pcm)
                data = transport.receive()
            except socket.timeout:
                continue
            except OSError:
                self._stop_event.wait(0.2)
                continue
            if data == b'K':
                last_ack = time.monotonic()
                self._latency_ms = max(0, (last_ack-last_ping)*1000)
                continue
            if len(data) < 2 or data[:1] != b'R':
                continue
            size = data[1]
            speaker = data[2:2+size].decode('utf-8', errors='replace')
            if self.peer and speaker != self.peer:
                continue
            pcm = data[2+size:]
            if not self.mixer.push(speaker, pcm):
                continue
            now_ts = time.time()
            previous = self._speaker_arrivals.get(speaker, 0)
            if previous > 0:
                gap_ms = (now_ts - previous) * 1000.0
                dev = abs(gap_ms - 20.0)
                self._avg_gap_ms = 0.95 * self._avg_gap_ms + 0.05 * gap_ms
                self._jitter_ms = 0.9 * self._jitter_ms + 0.1 * dev
                # rough loss proxy: big gaps
                miss = max(0.0, (gap_ms - 35.0) / 20.0)
                self._loss_score = min(100.0, 0.9 * self._loss_score + 10.0 * miss)
            self._last_recv_ts = now_ts
            self._speaker_arrivals = {name: stamp for name, stamp in self._speaker_arrivals.items() if now_ts-stamp < 5}
            self._speaker_arrivals[speaker] = now_ts

            try:
                arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
                self._peer_level = rms
                if rms >= self._voice_threshold:
                    self._last_peer_voice_ts = time.time()
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
        score = 100.0 - (
            jitter * 1.4
            + max(0.0, latency - 60.0) * 0.6
            + loss * 0.7
        )
        if score >= 75:
            quality = "Отличное"
        elif score >= 50:
            quality = "Хорошее"
        elif score >= 30:
            quality = "Среднее"
        else:
            quality = "Плохое"

        if self.transport is None:
            quality, score = "Переподключение", 0.0

        return {
            "mic_level": self._mic_level,
            "peer_level": self._peer_level,
            "me_speaking": me,
            "peer_speaking": peer,
            "latency_ms": round(latency, 1),
            "jitter_ms": round(jitter, 1),
            "buffer_frames": self.mixer.queued_frames(),
            "quality": quality,
            "quality_score": round(max(0.0, min(100.0, score)), 1),
        }
