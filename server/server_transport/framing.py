"""Bounded JSON framing with an absolute receive deadline."""
import json
import socket
import struct
import time

MAX_REQUEST = 256_000


def receive(connection, max_bytes=MAX_REQUEST, timeout=5):
    deadline=time.monotonic()+timeout
    def read(count):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError('Request deadline exceeded')
        connection.settimeout(remaining)
        return connection.recv(count)
    def exact(count):
        output=bytearray()
        while len(output)<count:
            part=read(count-len(output))
            if not part:
                raise ValueError('Неполный запрос')
            output.extend(part)
        return bytes(output)
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                raise ValueError('Повтор поля запроса')
            result[key]=value
        return result
    header=exact(4)
    if header[:1] in (b'{',b'['):
        # Legacy raw JSON is accepted only within the same size/time bounds.
        payload=bytearray(header)
        while True:
            connection.settimeout(min(.4,max(.001,deadline-time.monotonic())))
            if time.monotonic()>=deadline:
                raise TimeoutError('Request deadline exceeded')
            try:
                part=connection.recv(min(65536,max_bytes+1-len(payload)))
            except socket.timeout:
                break
            if not part:
                break
            payload.extend(part)
            if len(payload)>max_bytes:
                raise ValueError('Слишком большой запрос')
    else:
        length=struct.unpack('!I',header)[0]
        if not 0<length<=max_bytes:
            raise ValueError('Слишком большой запрос')
        payload=exact(length)
    try:
        return json.loads(payload,object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Некорректный JSON') from error
