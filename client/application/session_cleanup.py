"""Bounded best-effort logout/close requests without blocking Qt or owning widgets."""
from concurrent.futures import ThreadPoolExecutor
import json
import struct
import threading
import time
from transport.control import connect_api

_workers=ThreadPoolExecutor(max_workers=2,thread_name_prefix='nodys-session-cleanup')
_slots=threading.BoundedSemaphore(8)


def submit(endpoint, payload, timeout=1, pending=None):
    # Copy identity now; later login/logout must not change the request's user.
    request=dict(payload)
    if request.get('action') == 'logout' and pending is None:
        from application.logout_outbox import remember
        try:
            pending = remember(endpoint, request)
        except OSError:
            pass  # Still attempt immediate revocation if local storage is unavailable.
    if not _slots.acquire(blocking=False):
        return None
    try:
        return _workers.submit(_send,tuple(endpoint),request,timeout,pending)
    except RuntimeError:
        _slots.release()
        return None


def _send(endpoint, payload, timeout, pending=None):
    try:
        data=json.dumps(payload).encode('utf-8')
        with connect_api(*endpoint,timeout=timeout,configuration=pending[1]['configuration'] if pending else None) as connection:
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
                result = json.loads(exact(size))
                if pending and (result.get('status') == 'ok' or result.get('code') == 'session_invalid'):
                    from application.logout_outbox import acknowledge
                    acknowledge(pending[0], payload['token'])
                return result
    except Exception:
        return None
    finally:
        _slots.release()
