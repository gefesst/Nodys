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

    def save_message(self, from_user: str, to_user: str, text: str, client_message_id=None):
        with database_connection(self.database) as conn:
            if client_message_id:
                previous = conn.execute('SELECT id,to_user,text FROM messages WHERE from_user=? AND client_message_id=?', (from_user,client_message_id)).fetchone()
                if previous:
                    if previous[1:] != (to_user,text):
                        raise ValueError('Идентификатор сообщения уже использован')
                    return previous[0]
            cursor = conn.execute('INSERT INTO messages(from_user,to_user,text,is_read,client_message_id) VALUES(?,?,?,0,?)', (from_user,to_user,text,client_message_id))
            return cursor.lastrowid

    def get_page(self, user_a, user_b, limit=80, before_id=None, after_id=None):
        from .pagination import page
        with database_connection(self.database) as conn:
            result = page(conn, 'messages', '(from_user=? AND to_user=?) OR (from_user=? AND to_user=?)', (user_a,user_b,user_b,user_a), limit, before_id, after_id)
            result['read_through_id'] = conn.execute('SELECT COALESCE(MAX(id),0) FROM messages WHERE from_user=? AND to_user=? AND is_read=1', (user_a,user_b)).fetchone()[0]
            return result

    def get_messages(self, user_a: str, user_b: str, limit: int = 50) -> list:
        lim = max(1, min(500, int(limit or 50)))
        with database_connection(self.database) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """SELECT id, from_user, to_user, text, timestamp AS created_at, is_read
                   FROM messages
                   WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                   ORDER BY timestamp DESC, id DESC
                   LIMIT ?""",
                (user_a, user_b, user_b, user_a, lim),
            )
            # Клиенту по-прежнему отдаём в хронологическом порядке (старые -> новые).
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]

    def mark_chat_read(self, current_user: str, friend: str) -> None:
        with database_connection(self.database) as conn:
            conn.execute(
                "UPDATE messages SET is_read=1 WHERE from_user=? AND to_user=? AND is_read=0",
                (friend, current_user),
            )
            conn.commit()

    def get_unread_counts(self, current_user: str) -> Dict[str, int]:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT from_user, COUNT(*)
                   FROM messages
                   WHERE to_user=? AND is_read=0
                   GROUP BY from_user""",
                (current_user,),
            )
            return {row[0]: int(row[1]) for row in cur.fetchall()}
