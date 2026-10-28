"""Durable, private revocation queue retried on the next application launch."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from config import get_config_path, load_config

_lock=threading.RLock()


def _path():
    return Path(get_config_path()).with_name('pending_logout.json')


def _read(path):
    try:
        value=json.loads(path.read_text())
        if not isinstance(value, list): return []
        return [entry for entry in value if isinstance(entry,dict)
                and isinstance(entry.get('expires'), (int,float)) and entry['expires']>time.time()
                and isinstance(entry.get('payload'),dict) and isinstance(entry['payload'].get('token'),str)
                and isinstance(entry.get('configuration'),dict) and isinstance(entry.get('endpoint'),list)
                and len(entry['endpoint']) == 2 and isinstance(entry['endpoint'][0],str)
                and type(entry['endpoint'][1]) is int and 1 <= entry['endpoint'][1] <= 65535]
    except (OSError, ValueError, TypeError):
        return []


def _write(path, entries):
    descriptor, name=tempfile.mkstemp(prefix='.logout-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as output:
            json.dump(entries,output)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.remove(name)


def remember(endpoint, payload):
    path=_path()
    with _lock:
        entries=_read(path)
        entries=[entry for entry in entries if entry['payload'].get('token') != payload.get('token')]
        config=load_config()
        entry=dict(endpoint=list(endpoint),payload=dict(payload),
                   configuration={key:config[key] for key in ('api_tls','api_ca_file') if key in config},
                   expires=time.time()+30*86400)
        entries.append(entry)
        _write(path,entries)
    return path,entry


def acknowledge(path, token):
    with _lock:
        _write(path,[entry for entry in _read(path) if entry['payload'].get('token') != token])


def retry_pending():
    from application.session_cleanup import submit
    path=_path()
    with _lock:
        entries=_read(path)
    for entry in entries:
        submit(entry['endpoint'],entry['payload'],pending=(path,entry))
