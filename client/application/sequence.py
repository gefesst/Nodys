"""Reserve monotonic command numbers across process restarts and clock rollback."""
import threading
import time
from config import load_config, save_config

class SequenceClock:
    def __init__(self):
        self.last = 0
        self.limit = 0
        self.lock = threading.Lock()

    def next(self):
        with self.lock:
            value = max(time.time_ns(), self.last + 1)
            if value >= self.limit:
                config = load_config()
                value = max(value, int(config.get('voice_sequence_limit',0)) + 1)
                self.limit = value + 1000
                save_config({'voice_sequence_limit':self.limit})
            self.last = value
            return value

clock = SequenceClock()
