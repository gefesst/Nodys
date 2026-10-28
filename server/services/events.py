"""Durable event delivery and the compatibility in-memory notification queue."""
import datetime as dt
import threading
from collections import defaultdict, deque
from typing import Dict, Any
try:
    from ..storage.database import connect as database_connection
    from ..storage import events as event_store
except ImportError:
    from storage.database import connect as database_connection
    from storage import events as event_store

class EventService:
    def __init__(self, database, now, iso, max_events=200, ttl=180):
        self.database, self.now, self.iso = database, now, iso
        self.max_events, self.ttl = max_events, ttl
        self.lock = threading.Lock()
        self.pending = defaultdict(lambda: deque(maxlen=max_events))

    def push_event(self, login: str, event: Dict[str, Any]) -> None:
        if not login:
            return
        ev = dict(event)
        ev.setdefault("ts", self.iso(self.now()))
        with database_connection(self.database, timeout=10) as connection:
            event_store.append(connection, login, ev)
        self._publish_legacy_event(login, ev)

    def _publish_legacy_event(self, login, event):
        with self.lock:
            if login not in self.pending and len(self.pending) >= 8192:
                self.pending.pop(next(iter(self.pending)))
            self.pending[login].append(event)

    def pop_events(self, login: str) -> list:
        if not login:
            return []
        now = self.now()
        out = []
        with self.lock:
            q = self.pending.get(login)
            if not q:
                return []
            # prune by TTL
            for ev in q:
                try:
                    ts = dt.datetime.fromisoformat(ev.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=dt.timezone.utc)
                    if (now - ts).total_seconds() <= self.ttl:
                        out.append(ev)
                except Exception:
                    out.append(ev)
            # clear queue (one-shot delivery)
            self.pending.pop(login, None)
        return out
