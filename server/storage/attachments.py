"""Bounded, resumable attachment storage. Downloads require a published message."""
import base64
import hashlib
import re
import time
from shared.attachments import CHUNK_SIZE, MAX_FILE_SIZE, USER_QUOTA
from .database import connect, unit_of_work


def initialize(c):
    c.execute('''CREATE TABLE attachments (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
        size INTEGER NOT NULL, sha256 TEXT NOT NULL, peer TEXT NOT NULL,
        channel_id INTEGER NOT NULL, room_id INTEGER NOT NULL, created REAL NOT NULL,
        received INTEGER NOT NULL DEFAULT 0, published INTEGER NOT NULL DEFAULT 0)''')
    c.execute('CREATE INDEX idx_attachment_owner ON attachments(owner)')
    c.execute('''CREATE TABLE attachment_chunks (
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
        offset INTEGER NOT NULL, data BLOB NOT NULL, PRIMARY KEY(attachment_id,offset))''')
    c.execute('ALTER TABLE messages ADD COLUMN attachment_id TEXT')
    c.execute('ALTER TABLE channel_messages ADD COLUMN attachment_id TEXT')


def write_access(router, user, peer, cid, room):
    if cid:
        if not router.channels.valid_room(cid, room, 'text'):
            raise ValueError('Текстовый канал не найден')
        with connect(router.database) as c:
            if not router.channels.is_channel_member(cid, user) or not router.channels._can_send_text(c, cid, user):
                raise ValueError('Нет права отправлять файлы в этот канал')
    elif not peer or not router.friends.are_friends(user, peer):
        raise ValueError('Отправлять файлы можно только друзьям')


def dispatch(router, user, request):
    action = request['action']
    aid = request.get('attachment_id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', aid):
        raise ValueError('Некорректное вложение')
    # Same lock order as chat writes and membership mutations.
    with unit_of_work(router.database):
        session = router.accounts.get_session_by_token(request.get('token') or request.get('session_token') or '')
        if not session or session['login'] != user:
            raise ValueError('Сессия недействительна')
        with unit_of_work(router.messages.database) as c:
            if action == 'begin_attachment':
                peer, cid, room = request.get('to_user', ''), request.get('channel_id', 0), request.get('room_id', 0)
                write_access(router, user, peer, cid, room)
                name, size, digest = request.get('filename', ''), request.get('file_size', 0), request.get('sha256', '')
                if (not name or name in ('.', '..') or any(ord(x) < 32 or x in '/\\' for x in name)
                        or not 0 < size <= MAX_FILE_SIZE or not re.fullmatch(r'[a-f0-9]{64}', digest)):
                    raise ValueError('Некорректный файл или размер больше 10 МБ')
                prior = c.execute('SELECT owner,name,size,sha256,peer,channel_id,room_id FROM attachments WHERE id=?', (aid,)).fetchone()
                values = (user, name, size, digest, peer, cid, room)
                if prior:
                    if tuple(prior) != values:
                        raise ValueError('Идентификатор вложения уже занят')
                    return dict(status='ok')
                c.execute('DELETE FROM attachment_chunks WHERE attachment_id IN (SELECT id FROM attachments WHERE published=0 AND created<?)', (time.time()-86400,))
                c.execute('DELETE FROM attachments WHERE published=0 AND created<?', (time.time()-86400,))
                used = c.execute('SELECT COALESCE(SUM(size),0) FROM attachments WHERE owner=?', (user,)).fetchone()[0]
                if used + size > USER_QUOTA:
                    raise ValueError('Достигнут лимит хранения файлов (100 МБ)')
                c.execute('INSERT INTO attachments(id,owner,name,size,sha256,peer,channel_id,room_id,created) VALUES(?,?,?,?,?,?,?,?,?)', (aid, *values, time.time()))
                return dict(status='ok')
            row = c.execute('SELECT owner,name,size,sha256,peer,channel_id,room_id,received,published FROM attachments WHERE id=?', (aid,)).fetchone()
            if not row:
                raise ValueError('Вложение не найдено')
            owner, name, size, digest, peer, cid, room, received, published = row
            offset = request.get('offset', 0)
            if action == 'upload_attachment_chunk':
                if owner != user or published:
                    raise ValueError('Нет доступа к загрузке')
                write_access(router, user, peer, cid, room)
                try:
                    data = base64.b64decode(request.get('chunk', ''), validate=True)
                except (ValueError, TypeError):
                    raise ValueError('Некорректный блок файла') from None
                if not data or len(data) > CHUNK_SIZE or offset + len(data) > size:
                    raise ValueError('Некорректный размер блока')
                prior = c.execute('SELECT data FROM attachment_chunks WHERE attachment_id=? AND offset=?', (aid, offset)).fetchone()
                if prior:
                    if prior[0] != data:
                        raise ValueError('Блок файла уже записан с другим содержимым')
                    return dict(status='ok')
                if offset != received:
                    raise ValueError('Нарушен порядок загрузки')
                c.execute('INSERT INTO attachment_chunks VALUES(?,?,?)', (aid, offset, data))
                c.execute('UPDATE attachments SET received=received+? WHERE id=?', (len(data), aid))
                return dict(status='ok')
            # A guessable/leaked ID never grants download access.
            if not published:
                raise ValueError('Файл ещё не отправлен')
            if cid:
                exists = c.execute('SELECT 1 FROM channel_messages WHERE attachment_id=? AND channel_id=? AND room_id=?', (aid, cid, room)).fetchone()
                allowed = exists and router.channels.is_channel_member(cid, user) and router.channels.valid_room(cid, room, 'text')
            else:
                allowed = user in (owner, peer) and c.execute('SELECT 1 FROM messages WHERE attachment_id=? AND from_user=? AND to_user=?', (aid, owner, peer)).fetchone()
            if not allowed:
                raise ValueError('Нет доступа к файлу')
            block = c.execute('SELECT data FROM attachment_chunks WHERE attachment_id=? AND offset=?', (aid, offset)).fetchone()
            if block is None:
                raise ValueError('Блок файла не найден')
            return dict(status='ok', chunk=base64.b64encode(block[0]).decode('ascii'), filename=name, file_size=size, sha256=digest)


def bind(c, aid, owner, peer='', cid=0, room=0):
    if not aid:
        return
    row = c.execute('SELECT owner,peer,channel_id,room_id,size,received,sha256 FROM attachments WHERE id=?', (aid,)).fetchone()
    if not row or tuple(row[:4]) != (owner, peer, cid, room) or row[4] != row[5]:
        raise ValueError('Вложение не загружено или относится к другому диалогу')
    digest = hashlib.sha256()
    for data, in c.execute('SELECT data FROM attachment_chunks WHERE attachment_id=? ORDER BY offset', (aid,)):
        digest.update(data)
    if digest.hexdigest() != row[6]:
        raise ValueError('Файл повреждён при загрузке')
    c.execute('UPDATE attachments SET published=1 WHERE id=?', (aid,))


def enrich(c, rows):
    for row in rows:
        aid = row.get('attachment_id')
        if aid:
            meta = c.execute('SELECT name,size,sha256 FROM attachments WHERE id=? AND published=1', (aid,)).fetchone()
            if meta:
                row['attachment'] = dict(id=aid, name=meta[0], size=meta[1], sha256=meta[2])
    return rows
