"""Verified TLS for remote control connections; plaintext only on loopback."""
from contextlib import contextmanager
import ipaddress
import socket
import ssl
from config import load_config


def is_loopback(host):
    if host == 'localhost': return True
    try: return ipaddress.ip_address(host).is_loopback
    except ValueError: return False


@contextmanager
def connect_api(host, port, timeout=3.0, configuration=None):
    config = load_config() if configuration is None else configuration
    tls = config.get('api_tls', not is_loopback(host))
    if not tls and not is_loopback(host):
        raise ValueError('Удалённый сервер требует TLS')
    context = None
    if tls:
        context = ssl.create_default_context(cafile=config.get('api_ca_file') or None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    raw = socket.create_connection((host,int(port)),timeout=timeout)
    try:
        if context:
            with context.wrap_socket(raw,server_hostname=host) as connection:
                yield connection
        else:
            yield raw
    finally:
        raw.close()
