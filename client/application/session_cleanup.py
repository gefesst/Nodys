"""Bounded best-effort logout/close requests without blocking Qt or owning widgets."""
from concurrent.futures import ThreadPoolExecutor
import json
import struct
import threading
import time
from transport.control import connect_api

_workers=ThreadPoolExecutor(max_workers=2,thread_name_prefix='nodys-session-cleanup')
_slots=threading.BoundedSemaphore(8)


def submit(endpoint, payload, timeout=1):
    # Copy identity now; later login/logout must not change the request's user.
    request=dict(payload)
    if not _slots.acquire(blocking=False):
        return None
    try:
        return _workers.submit(_send,tuple(endpoint),request,timeout)
    except RuntimeError:
        _slots.release()
        return None


def _send(endpoint, payload, timeout):
    try:
        data=json.dumps(payload).encode('utf-8')
        with connect_api(*endpoint,timeout=timeout) as connection:
            connection.sendall(struct.pack('!I',len(data))+data)
            deadline=time.monotonic()+timeout
            def exact(count):
                result=b''
                while len(result)<count:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError()
                    connection.settimeout(remaining)
                    part=connection.recv(count-len(result))
                    if not part:raise ConnectionError()
                    result+=part
                return result
            size=struct.unpack('!I',exact(4))[0]
            if 0<size<=4096:
                return json.loads(exact(size))
    except Exception:
        return None
    finally:
        _slots.release()
