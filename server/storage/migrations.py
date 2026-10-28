"""Ordered SQLite migrations with transactional DDL and pre-upgrade snapshots."""
from pathlib import Path
import sqlite3
from contextlib import closing
import time
import uuid
from .database import connect
from . import events as event_store, voice_tickets


def _users_baseline(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
        login TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        nickname TEXT NOT NULL,
        avatar TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS friends (
        user_login TEXT,
        friend_login TEXT,
        PRIMARY KEY (user_login, friend_login)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS friend_requests (
        from_user TEXT,
        to_user TEXT,
        PRIMARY KEY (from_user, to_user)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        login TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        expires_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_call_pairs (
        user_a TEXT NOT NULL,
        user_b TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ringing',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_a, user_b)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        avatar TEXT DEFAULT '',
        owner_login TEXT NOT NULL,
        text_min_role TEXT NOT NULL DEFAULT 'member',
        voice_min_role TEXT NOT NULL DEFAULT 'member',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_members (
        channel_id INTEGER NOT NULL,
        login TEXT NOT NULL,
        joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        role TEXT NOT NULL DEFAULT 'member',
        PRIMARY KEY (channel_id, login)
        )
    """)
    cm_cols = [r[1] for r in c.execute('PRAGMA table_info(channel_members)').fetchall()]
    if 'role' not in cm_cols:
        c.execute("ALTER TABLE channel_members ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
    ch_cols = [r[1] for r in c.execute('PRAGMA table_info(channels)').fetchall()]
    if 'text_min_role' not in ch_cols:
        c.execute("ALTER TABLE channels ADD COLUMN text_min_role TEXT NOT NULL DEFAULT 'member'")
    if 'voice_min_role' not in ch_cols:
        c.execute("ALTER TABLE channels ADD COLUMN voice_min_role TEXT NOT NULL DEFAULT 'member'")
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_voice_presence (
        channel_id INTEGER NOT NULL,
        login TEXT NOT NULL,
        speaking INTEGER NOT NULL DEFAULT 0,
        last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (channel_id, login)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL,
        from_user TEXT NOT NULL,
        to_user TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS voice_presence_versions (
        token TEXT NOT NULL, channel_id INTEGER NOT NULL, sequence INTEGER NOT NULL,
        PRIMARY KEY(token, channel_id))
    """)
    c.execute('DELETE FROM voice_presence_versions WHERE token NOT IN (SELECT token FROM sessions)')
    event_store.initialize(conn)
    voice_tickets.initialize(conn)
    call_columns = {row[1] for row in c.execute('PRAGMA table_info(active_call_pairs)')}
    if 'caller_login' not in call_columns:
        c.execute("ALTER TABLE active_call_pairs ADD COLUMN caller_login TEXT NOT NULL DEFAULT ''")
    c.execute('CREATE INDEX IF NOT EXISTS idx_friends_user ON friends(user_login)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_friends_friend ON friends(friend_login)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_fr_to ON friend_requests(to_user)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_login ON sessions(login)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels(owner_login)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_channel_members_login ON channel_members(login)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_channel_members_channel ON channel_members(channel_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ch_voice_presence_channel ON channel_voice_presence(channel_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ch_voice_presence_seen ON channel_voice_presence(last_seen)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ch_inv_to_status ON channel_invites(to_user, status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ch_inv_channel_status ON channel_invites(channel_id, status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_active_call_pairs_updated ON active_call_pairs(updated_at)')

def _chat_baseline(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user TEXT NOT NULL,
        to_user TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER DEFAULT 0
        )
    """)
    cols = [r[1] for r in c.execute('PRAGMA table_info(messages)').fetchall()]
    if 'is_read' not in cols:
        c.execute('ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0')
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL,
        from_user TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute('CREATE INDEX IF NOT EXISTS idx_msg_pair_time ON messages(from_user, to_user, timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_msg_to_read ON messages(to_user, is_read)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ch_msg_channel_time ON channel_messages(channel_id, timestamp)')


def _call_heartbeats(connection):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(active_call_pairs)')}
    for name in ('seen_a', 'seen_b'):
        if name not in columns:
            connection.execute(f"ALTER TABLE active_call_pairs ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            connection.execute(f'UPDATE active_call_pairs SET {name}=updated_at')


def _receipts(connection):
    try:
        from ..services.mutations import initialize
    except ImportError:
        from services.mutations import initialize
    initialize(connection)


def _channel_cleanup(connection):
    connection.execute("CREATE TABLE channel_cleanup (channel_id INTEGER PRIMARY KEY)")


MIGRATIONS = {
    'users': [('baseline', _users_baseline), ('call_heartbeats', _call_heartbeats), ('mutation_receipts', _receipts), ('channel_cleanup', _channel_cleanup)],
    'chat': [('baseline', _chat_baseline), ('mutation_receipts', _receipts)],
}


def migrate(path, kind):
    """Fail closed on unknown versions; never swallow an ALTER/DDL failure.

    Backup uses SQLite's snapshot API (including WAL data), not a file copy.
    All pending migrations and their ledger entries commit as one transaction.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = MIGRATIONS[kind]
    with connect(path, timeout=10) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        applied = list(connection.execute('SELECT version,name FROM schema_migrations ORDER BY version')) if 'schema_migrations' in tables else []
        expected = [(i+1, name) for i,(name,_) in enumerate(migrations)]
        if applied != expected[:len(applied)]:
            raise RuntimeError(f'Unsupported or inconsistent {kind} database version; no migration performed')
        if len(applied) == len(migrations):
            return
        if tables:
            folder = path.parent/'backups'
            folder.mkdir(exist_ok=True, mode=0o700)
            backup = folder/f'{path.name}.{time.time_ns()}.{uuid.uuid4().hex[:8]}.sqlite3'
            with closing(sqlite3.connect(backup)) as destination:
                backup.chmod(0o600)
                connection.backup(destination)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL)')
        # Re-read under the write lock: another process may have just migrated.
        applied = list(connection.execute('SELECT version,name FROM schema_migrations ORDER BY version'))
        if applied != expected[:len(applied)]:
            raise RuntimeError('Database version changed unexpectedly')
        for version, (name, upgrade) in enumerate(migrations, 1):
            if version <= len(applied):
                continue
            upgrade(connection)
            connection.execute('INSERT INTO schema_migrations(version,name) VALUES(?,?)',(version,name))
