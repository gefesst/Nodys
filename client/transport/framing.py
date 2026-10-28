"""Bounded response decoding with a total deadline, including legacy JSON."""
import json
import socket
import struct
import time


def receive(connection, max_bytes=10_000_000, timeout=5):
    deadline = time.monotonic() + timeout
    def read(count):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Response deadline exceeded')
        connection.settimeout(remaining)
        return connection.recv(count)
    def exact(count):
        data = bytearray()
        while len(data) < count:
            part = read(count-len(data))
            if not part:
                raise ConnectionError('Incomplete server response')
            data.extend(part)
        return bytes(data)
    header = exact(4)
    if header[:1] in (b'{', b'['):
        data = bytearray(header)
        while len(data) <= max_bytes:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Response deadline exceeded')
            connection.settimeout(min(.4, remaining))
            try:
                part = connection.recv(min(65536,max_bytes+1-len(data)))
            except socket.timeout:
                break
            if not part:
                break
            data.extend(part)
        if len(data)>max_bytes:
            raise ValueError('Response too large')
    else:
        size = struct.unpack('!I',header)[0]
        if not 0<size<=max_bytes:
            raise ValueError('Invalid response length')
        data = exact(size)
    try:
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid server response') from error
    if not isinstance(value, dict):
        raise ValueError('Expected a response object')
    return value
