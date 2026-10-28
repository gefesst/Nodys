"""Real encrypted UDP path with synthetic PCM in place of microphone/speaker devices."""

import threading, time
import numpy as np
from voice_client import VoiceClient
from application import voice_session


class SyntheticVoiceClient(VoiceClient):
    instances = []

    def _start_audio(self):
        self.ticks = 0
        self.nonzero = 0
        self.gaps = []
        self.callback_ms = []
        self.empty_after_warmup = 0
        self.instances.append(self)
        self.audio_worker = threading.Thread(
            target=self._audio_loop, daemon=True, name="prototype-audio-clock"
        )
        self.audio_worker.start()

    def _audio_loop(self):
        samples = (
            (np.sin(np.arange(320) * 2 * np.pi * 440 / 16000) * 2500)
            .astype(np.int16)
            .reshape(-1, 1)
        )
        output = np.zeros((320, 1), dtype=np.int16)
        deadline = time.perf_counter()
        last = deadline
        while self.running and not self._stop_event.is_set():
            now = time.perf_counter()
            self.gaps.append((now - last) * 1000)
            last = now
            t = now
            self._capture_cb(samples, 320, None, None)
            self._play_cb(output, 320, None, None)
            self.callback_ms.append((time.perf_counter() - t) * 1000)
            self.ticks += 1
            if np.any(output):
                self.nonzero += 1
            elif self.ticks > 50:
                self.empty_after_warmup += 1
            deadline += 0.02
            self._stop_event.wait(max(0, deadline - time.perf_counter()))

    def stop(self):
        super().stop()
        if (
            hasattr(self, "audio_worker")
            and self.audio_worker is not threading.current_thread()
        ):
            self.audio_worker.join(1)

    def metrics(self):
        def p95(v):
            return round(float(np.percentile(v, 95)), 3) if v else None

        return dict(
            login=self.login,
            ticks=self.ticks,
            nonzero_output_frames=self.nonzero,
            empty_after_warmup=self.empty_after_warmup,
            clock_gap_p95_ms=p95(self.gaps[1:]),
            clock_gap_max_ms=round(max(self.gaps or [0]), 3),
            callback_p95_ms=p95(self.callback_ms),
            callback_max_ms=round(max(self.callback_ms or [0]), 3),
        )


# Injection is confined to this experimental process; repository code is untouched.
voice_session.VoiceClient = SyntheticVoiceClient
VoiceSession = voice_session.VoiceSession
