"""Explicit reaction state: retrying a write never toggles it twice."""
import sqlite3
try:
    from .message_actions import scope
    from ..storage.database import connect
    from ..storage.message_content import enrich
except ImportError:
    from services.message_actions import scope
    from storage.database import connect
    from storage.message_content import enrich
from shared.reactions import REACTIONS


def set_reaction(router, user, data):
    table, where, params = scope(router, user, data)
    emoji = data.get('emoji')
    if emoji not in REACTIONS or type(data.get('active')) is not bool or not data.get('message_id'):
        raise ValueError('Некорректная реакция')
    if data.get('channel_id'):
        with connect(router.database) as users:
            if not router.channels._can_send_text(users, data['channel_id'], user):
                raise ValueError('Нет прав реагировать в этом канале')
    elif not router.friends.are_friends(user, data['to_user']):
        raise ValueError('Реакции доступны в переписке с другом')
    with connect(router.messages.database) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f'SELECT * FROM {table} WHERE ({where}) AND id=?', (*params, data['message_id'])).fetchone()  # nosec B608: fixed scope.
        if row is None or row['deleted_at']:
            raise ValueError('Сообщение удалено или недоступно')
        key = (table, row['id'], user, emoji)
        if data['active']:
            changed = conn.execute('INSERT OR IGNORE INTO message_reactions VALUES(?,?,?,?)', key).rowcount
        else:
            changed = conn.execute('DELETE FROM message_reactions WHERE kind=? AND message_id=? AND login=? AND emoji=?', key).rowcount
        if changed:
            conn.execute(f'UPDATE {table} SET revision=revision+1 WHERE id=?', (row['id'],))  # nosec B608: fixed scope.
        updated = conn.execute(f'SELECT *,timestamp AS created_at FROM {table} WHERE id=?', (row['id'],)).fetchone()  # nosec B608: fixed scope.
        return dict(status='ok', message=enrich(conn, [dict(updated)], user)[0])
