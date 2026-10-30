"""File IO and bounded network transfer stay outside the GUI thread."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Qt, QCoreApplication
from shared.attachments import MAX_FILE_SIZE, CHUNK_SIZE


class AttachmentTransfer(QObject):
    progress = Signal(int)
    finished = Signal(dict)
    _result = Signal(dict)
    _inflight = set()

    def __init__(self, token, scope, path, metadata=None, upload_id=None, preview=False):
        super().__init__(QCoreApplication.instance())
        from settings import get_api_endpoint
        self.host, self.port = get_api_endpoint()
        self.token, self.scope, self.path, self.metadata = token, dict(scope), Path(path) if path is not None else None, metadata
        self.preview = preview
        self.upload_id = upload_id or uuid.uuid4().hex
        self.cancelled = threading.Event()
        self._result.connect(self._deliver, Qt.QueuedConnection)
        QCoreApplication.instance().aboutToQuit.connect(self.cancelled.set)

    def start(self):
        self._inflight.add(self)
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self.cancelled.set()

    def request(self, **payload):
        if self.cancelled.is_set():
            raise ValueError('Передача отменена')
        from transport.control import connect_api
        from network import send_json_packet, recv_json_packet
        with connect_api(self.host, self.port) as sock:
            send_json_packet(sock, dict(payload, token=self.token))
            response = recv_json_packet(sock)
        if not response or response.get('status') != 'ok':
            raise ValueError((response or {}).get('message', 'Нет ответа от сервера'))
        return response

    def _run(self):
        try:
            result = self.preview_image() if self.preview else self.download() if self.metadata else self.upload()
        except Exception as error:
            result = dict(status='error', message=str(error))
        self._result.emit(result)

    def _deliver(self, result):
        self._inflight.discard(self)
        if not self.cancelled.is_set():
            self.finished.emit(result)
        self.deleteLater()

    def upload(self):
        with self.path.open('rb') as source:
            if not 0 < os.fstat(source.fileno()).st_size <= MAX_FILE_SIZE:
                raise ValueError('Выберите файл от 1 байта до 10 МБ')
            data = source.read(MAX_FILE_SIZE + 1)
        if not 0 < len(data) <= MAX_FILE_SIZE:
            raise ValueError('Файл пустой или больше 10 МБ')
        aid = self.upload_id
        digest = hashlib.sha256(data).hexdigest()
        self.request(action='begin_attachment', attachment_id=aid, filename=self.path.name,
                     file_size=len(data), sha256=digest, **self.scope)
        for offset in range(0, len(data), CHUNK_SIZE):
            block = data[offset:offset+CHUNK_SIZE]
            self.request(action='upload_attachment_chunk', attachment_id=aid, offset=offset,
                         chunk=base64.b64encode(block).decode('ascii'))
            self.progress.emit(int(100*(offset+len(block))/len(data)))
        return dict(status='ok', attachment=dict(id=aid, name=self.path.name, size=len(data), sha256=digest))

    def download(self):
        meta = self.metadata
        size = meta['size']
        if not 0 < size <= MAX_FILE_SIZE:
            raise ValueError('Некорректный размер вложения')
        digest = hashlib.sha256()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.noda-download-', delete=False) as output:
                temporary = output.name
                offset = 0
                while offset < size:
                    response = self.request(action='download_attachment_chunk', attachment_id=meta['id'], offset=offset)
                    block = base64.b64decode(response['chunk'], validate=True)
                    if not block or len(block) > CHUNK_SIZE or offset+len(block) > size:
                        raise ValueError('Некорректный блок файла')
                    output.write(block)
                    digest.update(block)
                    offset += len(block)
                    self.progress.emit(int(100*offset/size))
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != meta['sha256']:
                raise ValueError('Файл повреждён при передаче')
            if self.cancelled.is_set():
                raise ValueError('Передача отменена')
            os.replace(temporary, self.path)
            temporary = None
            return dict(status='ok')
        finally:
            if temporary:
                os.unlink(temporary)

    def preview_image(self):
        """Decode a bounded raster in the worker; no save dialog or disk file."""
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize
        from PySide6.QtGui import QImageReader
        meta = self.metadata
        size = meta['size']
        if not 0 < size <= MAX_FILE_SIZE:
            raise ValueError('Некорректный размер изображения')
        data = bytearray()
        while len(data) < size:
            response = self.request(action='download_attachment_chunk', attachment_id=meta['id'], offset=len(data))
            block = base64.b64decode(response['chunk'], validate=True)
            if not block or len(block) > CHUNK_SIZE or len(data)+len(block) > size:
                raise ValueError('Некорректный блок изображения')
            data.extend(block)
        if hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise ValueError('Изображение повреждено при передаче')
        buffer = QBuffer()
        buffer.setData(QByteArray(bytes(data)))
        buffer.open(QIODevice.ReadOnly)
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        reader.setAutoTransform(True)
        dimensions = reader.size()
        if (bytes(reader.format()) not in (b'png', b'jpeg', b'webp', b'gif', b'bmp')
                or not 0 < dimensions.width()*dimensions.height() <= 40000000):
            raise ValueError('Это изображение нельзя показать. Его можно сохранить как файл.')
        if max(dimensions.width(), dimensions.height()) > 2048:
            reader.setScaledSize(dimensions.scaled(QSize(2048, 2048), Qt.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise ValueError('Не удалось прочитать изображение')
        return dict(status='ok', image=image)
