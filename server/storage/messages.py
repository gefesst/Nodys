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

    def save_message(self, from_user: str, to_user: str, text: str) -> bool:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO messages(from_user, to_user, text, is_read) VALUES(?,?,?,0)",
                (from_user, to_user, text),
            )
            conn.commit()
        return True

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
