"""Bounded process-local sliding-window admission, keyed by socket peer IP."""
from collections import deque
import threading
import time


class WindowLimiter:
    def __init__(self, limit, seconds, max_keys=4096, clock=time.monotonic):
        self.limit, self.seconds, self.max_keys = limit, seconds, max_keys
        self.clock=clock
        self.entries={}
        self.lock=threading.Lock()

    def allow(self, key):
        now=self.clock()
        with self.lock:
            queue=self.entries.get(key)
            if queue is None:
                if len(self.entries)>=self.max_keys:
                    self.entries={k:q for k,q in self.entries.items() if q and now-q[-1]<self.seconds}
                if len(self.entries)>=self.max_keys:
                    return False  # never evict a live limit to admit a new attacker
                queue=self.entries.setdefault(key,deque())
            while queue and now-queue[0]>=self.seconds:
                queue.popleft()
            if len(queue)>=self.limit:
                return False
            queue.append(now)
            return True


class Admission:
    def __init__(self):
        self.connections=WindowLimiter(120,1)
        self.auth_ip=WindowLimiter(30,60)
        self.auth_pair=WindowLimiter(8,60)
        self.auth_global=WindowLimiter(120,60,max_keys=1)

    def allow_auth(self, address, login):
        # Both login and registration share the expensive password-work budget.
        return (self.auth_ip.allow(address) and self.auth_pair.allow((address,login))
                and self.auth_global.allow('all'))
