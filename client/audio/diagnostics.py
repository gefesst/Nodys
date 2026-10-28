"""Bounded counters only: no PCM recording, disk I/O or logging in callbacks."""

import time


class AudioDiagnostics:
    def __init__(self):
        self.started = time.monotonic()
        self.values = dict(
            capture_callbacks=0,
            playback_callbacks=0,
            input_overflows=0,
            output_underflows=0,
            capture_max_us=0,
            playback_max_us=0,
            capture_gap_max_us=0,
            playback_gap_max_us=0,
            outgoing_dropped=0,
            outgoing_high_water=0,
            packets_sent=0,
            packets_received=0,
            rejected_audio=0,
            socket_errors=0,
            reconnect_attempts=0,
            reconnect_failures=0,
        )
        self.last = {"capture": 0, "playback": 0}

    def begin(self, kind, status):
        now = time.perf_counter_ns()
        previous = self.last[kind]
        self.last[kind] = now
        self.values[kind + "_callbacks"] += 1
        if previous:
            self.values[kind + "_gap_max_us"] = max(
                self.values[kind + "_gap_max_us"], (now - previous) // 1000
            )
        if kind == "capture" and getattr(status, "input_overflow", False):
            self.values["input_overflows"] += 1
        if kind == "playback" and getattr(status, "output_underflow", False):
            self.values["output_underflows"] += 1
        return now

    def end(self, kind, started):
        self.values[kind + "_max_us"] = max(
            self.values[kind + "_max_us"], (time.perf_counter_ns() - started) // 1000
        )

    def snapshot(self):
        return dict(
            self.values, elapsed_seconds=round(time.monotonic() - self.started, 2)
        )
