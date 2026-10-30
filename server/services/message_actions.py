"""Scoped message mutations and bounded refreshes of already loaded history."""
import sqlite3
try:
    from ..storage.database import connect
    from ..storage.message_content import enrich
except ImportError:
    from storage.database import connect
    from storage.message_content import enrich


def scope(router, user, data):
    cid = data.get('channel_id')
    if cid:
        room = data.get('room_id', 0)
        if not router.channels.is_channel_member(cid, user) or not router.channels.valid_room(cid, room, 'text'):
            raise ValueError('Нет доступа к текстовому каналу')
        return 'channel_messages', 'channel_id=? AND room_id=?', (cid, room)
    peer = data.get('to_user', '').strip()
    if not peer or peer == user:
        raise ValueError('Не указан собеседник')
    return 'messages', '(from_user=? AND to_user=?) OR (from_user=? AND to_user=?)', (user, peer, peer, user)


def refresh(router, user, data):
    table, where, params = scope(router, user, data)
    versions = data.get('visible_versions', '')
    if not versions:
        return []
    values = versions.split(',')
    seen = {}
    if len(values) > 240:
        raise ValueError('Некорректное окно истории')
    for value in values:
        parts = value.split(':')
        if len(parts) != 2 or any(not p.isascii() or not p.isdigit() or int(p) >= 2**63 for p in parts):
            raise ValueError('Некорректное окно истории')
        identity, revision = map(int, parts)
        if identity <= 0:
            raise ValueError('Некорректное окно истории')
        seen[identity] = revision
    with connect(router.messages.database) as conn:
        conn.row_factory = sqlite3.Row
        slots = ','.join('?' for _ in seen)
        rows = conn.execute(
            f'SELECT *,timestamp AS created_at FROM {table} WHERE ({where}) AND id IN ({slots})',  # nosec B608: scope returns fixed SQL; ids bound.
            (*params, *seen)).fetchall()
        return enrich(conn, [dict(row) for row in rows if row['revision'] > seen[row['id']]])


def mutate(router, user, data):
    table, where, params = scope(router, user, data)
    identity = data.get('message_id')
    if identity is None or 'expected_revision' not in data:
        raise ValueError('Не указано сообщение или его версия')
    with connect(router.messages.database) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f'SELECT * FROM {table} WHERE ({where}) AND id=?',  # nosec B608: fixed scoped identifiers.
            (*params, identity)).fetchone()
        if row is None or row['from_user'] != user:
            raise ValueError('Изменять можно только свои сообщения')
        if row['revision'] != data['expected_revision']:
            return dict(status='error', code='message_changed', message='Сообщение уже изменилось. Обновите его и повторите действие.')
        if row['deleted_at']:
            raise ValueError('Сообщение уже удалено')
        if data['action'] == 'edit_message':
            if data.get('channel_id'):
                with connect(router.database) as users:
                    if not router.channels._can_send_text(users, data['channel_id'], user):
                        raise ValueError('Нет прав изменять сообщения в этом канале')
            elif not router.friends.are_friends(user, data['to_user']):
                raise ValueError('Изменять сообщения можно только в переписке с другом')
            text = data.get('text', '').strip()
            if not text and not row['attachment_id']:
                raise ValueError('Сообщение не может быть пустым')
            conn.execute(
                f"UPDATE {table} SET text=?,edited_at=strftime('%Y-%m-%d %H:%M:%f','now'),revision=revision+1 WHERE id=?",  # nosec B608: fixed table.
                (text, identity))
        else:
            conn.execute(
                f"UPDATE {table} SET text='',attachment_id=NULL,deleted_at=strftime('%Y-%m-%d %H:%M:%f','now'),revision=revision+1 WHERE id=?",  # nosec B608: fixed table.
                (identity,))
            aid = row['attachment_id']
            if aid and not conn.execute('SELECT 1 FROM messages WHERE attachment_id=? UNION ALL SELECT 1 FROM channel_messages WHERE attachment_id=? LIMIT 1', (aid, aid)).fetchone():
                conn.execute('DELETE FROM attachment_chunks WHERE attachment_id=?', (aid,))
                conn.execute('DELETE FROM attachments WHERE id=?', (aid,))
        # Quote changes must reach clients even when the original is outside their window.
        conn.execute(f'UPDATE {table} SET revision=revision+1 WHERE reply_to_id=?', (identity,))  # nosec B608: fixed table.
        updated = conn.execute(
            f'SELECT *,timestamp AS created_at FROM {table} WHERE id=?',  # nosec B608: fixed table.
            (identity,)).fetchone()
        return dict(status='ok', message=enrich(conn, [dict(updated)])[0])
