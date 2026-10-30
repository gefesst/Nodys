"""MessageRepository: explicit dependencies, independent of socket dispatch."""
import sqlite3
from typing import Dict
try:
    from ..storage.database import connect as database_connection
except ImportError:
    from storage.database import connect as database_connection
class MessageRepository:
    def __init__(self, database):
        self.database = database

    def save_message(self, from_user: str, to_user: str, text: str, client_message_id=None, attachment_id=None, reply_to_id=None):
        with database_connection(self.database) as conn:
            if client_message_id:
                previous = conn.execute('SELECT id,to_user,text,attachment_id,reply_to_id FROM messages WHERE from_user=? AND client_message_id=?', (from_user,client_message_id)).fetchone()
                if previous:
                    if previous[1:] != (to_user,text,attachment_id,reply_to_id):
                        raise ValueError('Идентификатор сообщения уже использован')
                    return previous[0]
            from .message_content import validate_reply
            validate_reply(conn, dict(from_user=from_user, to_user=to_user), reply_to_id)
            from .attachments import bind
            bind(conn, attachment_id, from_user, peer=to_user)
            cursor = conn.execute('INSERT INTO messages(from_user,to_user,text,is_read,client_message_id,attachment_id,reply_to_id) VALUES(?,?,?,0,?,?,?)', (from_user,to_user,text,client_message_id,attachment_id,reply_to_id))
            return cursor.lastrowid

    def get_page(self, user_a, user_b, limit=80, before_id=None, after_id=None, around_id=None):
        from .pagination import page
        with database_connection(self.database) as conn:
            result = page(conn, 'messages', '(from_user=? AND to_user=?) OR (from_user=? AND to_user=?)', (user_a,user_b,user_b,user_a), limit, before_id, after_id, around_id)
            result['read_through_id'] = conn.execute('SELECT COALESCE(MAX(id),0) FROM messages WHERE from_user=? AND to_user=? AND is_read=1', (user_a,user_b)).fetchone()[0]
            return result

    def get_messages(self, user_a: str, user_b: str, limit: int = 50) -> list:
        lim = max(1, min(500, int(limit or 50)))
        with database_connection(self.database) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """SELECT id, from_user, to_user, text, timestamp AS created_at, is_read, attachment_id, revision, edited_at, deleted_at, reply_to_id
                   FROM messages
                   WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                   ORDER BY timestamp DESC, id DESC
                   LIMIT ?""",
                (user_a, user_b, user_b, user_a, lim),
            )
            # Клиенту по-прежнему отдаём в хронологическом порядке (старые -> новые).
            rows = cur.fetchall()
            from .message_content import enrich
            return enrich(conn, [dict(r) for r in reversed(rows)])

    def mark_chat_read(self, current_user: str, friend: str, through_id=None) -> None:
        with database_connection(self.database) as conn:
            if through_id is None:
                conn.execute(
                    "UPDATE messages SET is_read=1 WHERE from_user=? AND to_user=? AND is_read=0",
                    (friend, current_user),
                )
            else:
                conn.execute(
                    "UPDATE messages SET is_read=1 WHERE from_user=? AND to_user=? AND is_read=0 AND id<=?",
                    (friend, current_user, through_id),
                )
            conn.commit()

    def get_unread_counts(self, current_user: str) -> Dict[str, int]:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT from_user, COUNT(*)
                   FROM messages
                   WHERE to_user=? AND is_read=0 AND deleted_at IS NULL
                   GROUP BY from_user""",
                (current_user,),
            )
            return {row[0]: int(row[1]) for row in cur.fetchall()}

    def get_dialog_summaries(self, current_user):
        """Return only the authenticated user's latest message for each peer."""
        with database_connection(self.database) as conn:
            rows = conn.execute(
                """WITH owned AS (
                       SELECT to_user AS peer, id FROM messages WHERE from_user=?
                       UNION ALL
                       SELECT from_user AS peer, id FROM messages WHERE to_user=?
                   ), latest AS (SELECT peer, MAX(id) AS id FROM owned GROUP BY peer)
                   SELECT latest.peer, m.from_user, CASE WHEN m.deleted_at IS NOT NULL THEN 'Сообщение удалено' WHEN m.text='' AND m.attachment_id IS NOT NULL THEN '📎 ' || COALESCE((SELECT name FROM attachments WHERE id=m.attachment_id),'Файл') ELSE substr(m.text,1,160) END, m.timestamp
                   FROM latest JOIN messages m ON m.id=latest.id""",
                (current_user, current_user),
            )
            return {peer: {"text": text, "timestamp": timestamp,
                           "outgoing": sender == current_user}
                    for peer, sender, text, timestamp in rows}
