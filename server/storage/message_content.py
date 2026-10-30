"""Live, bounded reply previews; originals are always scoped to the same chat."""
from .attachments import enrich as enrich_attachments


def original(c, row, identity):
    if 'channel_id' in row:
        return c.execute('SELECT id,from_user,text,attachment_id,deleted_at,revision FROM channel_messages WHERE id=? AND channel_id=? AND room_id=?',
                         (identity, row['channel_id'], row['room_id'])).fetchone()
    return c.execute('SELECT id,from_user,text,attachment_id,deleted_at,revision FROM messages WHERE id=? AND ((from_user=? AND to_user=?) OR (from_user=? AND to_user=?))',
                     (identity, row['from_user'], row['to_user'], row['to_user'], row['from_user'])).fetchone()


def validate_reply(c, row, identity):
    if identity is not None:
        target = original(c, row, identity)
        if target is None or target[4]:
            raise ValueError('Исходное сообщение удалено или недоступно в этой переписке')


def enrich(c, rows):
    enrich_attachments(c, rows)
    for row in rows:
        identity = row.get('reply_to_id')
        if not identity or row.get('deleted_at'):
            continue
        target = original(c, row, identity)
        if target is None or target[4]:
            row['reply'] = dict(id=identity, author='', text='Сообщение удалено', deleted=True)
            continue
        text = target[2]
        if not text and target[3]:
            meta = c.execute('SELECT name FROM attachments WHERE id=?', (target[3],)).fetchone()
            text = '📎 ' + (meta[0] if meta else 'Вложение')
        row['reply'] = dict(id=identity, author=target[1], text=text[:200], deleted=False)
    return rows
