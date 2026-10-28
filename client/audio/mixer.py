"""Bounded per-speaker PCM queues and saturating multi-speaker playback."""
from collections import deque
import threading
import time
import numpy as np

class PcmMixer:
    def __init__(self, frame_samples=320, max_speakers=32, max_frames=8):
        self.frame_samples = frame_samples
        self.max_speakers = max_speakers
        self.max_frames = max_frames
        self.streams = {}
        self.lock = threading.Lock()

    def push(self, speaker, pcm):
        if not speaker or len(pcm) != self.frame_samples * 2:
            return False
        now = time.monotonic()
        with self.lock:
            for name in list(self.streams):
                if now-self.streams[name][1] > 5:
                    del self.streams[name]
            if speaker not in self.streams and len(self.streams) >= self.max_speakers:
                return False
            frames = self.streams.get(speaker, (deque(maxlen=self.max_frames),now))[0]
            frames.append(bytes(pcm))
            self.streams[speaker] = frames, now
        return True

    def mix(self):
        combined = np.zeros(self.frame_samples,dtype=np.int32)
        with self.lock:
            for frames, _ in self.streams.values():
                if frames:
                    combined += np.frombuffer(frames.popleft(),dtype='<i2').astype(np.int32)
        return np.clip(combined,-32768,32767).astype(np.int16)

    def clear(self):
        with self.lock: self.streams.clear()

    def queued_frames(self):
        with self.lock: return sum(len(frames) for frames,_ in self.streams.values())
