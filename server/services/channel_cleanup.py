"""Retryable cross-database deletion; membership revocation commits first."""
import logging
import sqlite3
try:
    from ..storage.database import connect
except ImportError:
    from storage.database import connect


def drain(users_db, chat_db):
    try:
        with connect(users_db, timeout=1) as users:
            pending = users.execute('SELECT channel_id FROM channel_cleanup LIMIT 100').fetchall()
        for (channel_id,) in pending:
            with connect(chat_db, timeout=1) as chat:
                # All file data and history share one transaction. Do not rely on
                # SQLite foreign-key enforcement being enabled on this connection.
                chat.execute('DELETE FROM attachment_chunks WHERE attachment_id IN '
                             '(SELECT id FROM attachments WHERE channel_id=?)', (channel_id,))
                chat.execute('DELETE FROM attachments WHERE channel_id=?', (channel_id,))
                chat.execute('DELETE FROM channel_messages WHERE channel_id=?', (channel_id,))
            with connect(users_db, timeout=1) as users:
                users.execute('DELETE FROM channel_cleanup WHERE channel_id=?', (channel_id,))
        return True
    except sqlite3.Error:
        logging.getLogger(__name__).warning('Channel history cleanup deferred; persisted retry remains pending')
        return False
