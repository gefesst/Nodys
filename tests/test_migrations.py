import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from test_foundation import load
from storage import migrations
from storage.database import connect


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database=Path(self.folder.name)/'users.db'

    def test_legacy_upgrade_preserves_data_and_creates_snapshot(self):
        with connect(self.database) as connection:
            connection.execute('CREATE TABLE users(login TEXT PRIMARY KEY,password TEXT NOT NULL,nickname TEXT NOT NULL,avatar TEXT)')
            connection.execute("INSERT INTO users VALUES('alice','existing-hash','Alice','existing-avatar')")
            connection.execute('CREATE TABLE channel_members(channel_id INTEGER, login TEXT, joined_at TEXT, PRIMARY KEY(channel_id,login))')
            connection.execute("INSERT INTO channel_members VALUES(1,'alice','old-date')")
            connection.execute('CREATE TABLE channels(id INTEGER PRIMARY KEY,code TEXT,name TEXT,avatar TEXT,owner_login TEXT,created_at TEXT)')
            connection.execute("INSERT INTO channels VALUES(1,'code','old-channel','','alice','old-date')")
        migrations.migrate(self.database,'users')
        with connect(self.database) as connection:
            self.assertEqual(connection.execute('SELECT password,avatar FROM users').fetchone(),('existing-hash','existing-avatar'))
            self.assertEqual(connection.execute('SELECT role FROM channel_members').fetchone(),('member',))
            self.assertEqual(connection.execute('SELECT voice_min_role FROM channels').fetchone(),('member',))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0],len(migrations.MIGRATIONS['users']))
        backups=list((self.database.parent/'backups').glob('*.sqlite3'))
        self.assertEqual(len(backups),1)
        with connect(backups[0]) as connection:
            self.assertEqual(connection.execute('SELECT nickname FROM users').fetchone(),('Alice',))
            self.assertNotIn('role',[row[1] for row in connection.execute('PRAGMA table_info(channel_members)')])
        migrations.migrate(self.database,'users')
        self.assertEqual(len(list((self.database.parent/'backups').glob('*.sqlite3'))),1)

    def test_failed_migration_rolls_back_schema_and_ledger(self):
        migrations.migrate(self.database,'users')
        def broken(connection):
            connection.execute('CREATE TABLE should_rollback(id INTEGER)')
            raise RuntimeError('synthetic migration failure')
        steps=migrations.MIGRATIONS['users']+[('broken',broken)]
        with patch.dict(migrations.MIGRATIONS,users=steps):
            with self.assertRaises(RuntimeError):migrations.migrate(self.database,'users')
        with connect(self.database) as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchone())
            self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],len(migrations.MIGRATIONS['users']))

    def test_future_schema_is_rejected_without_changes(self):
        migrations.migrate(self.database,'users')
        with connect(self.database) as connection:
            connection.execute("INSERT INTO schema_migrations VALUES(?,'future')",(len(migrations.MIGRATIONS['users'])+1,))
        with self.assertRaises(RuntimeError):migrations.migrate(self.database,'users')
        self.assertFalse((self.database.parent/'backups').exists())

    def test_old_messages_survive_chat_upgrade(self):
        with connect(self.database) as connection:
            connection.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,from_user TEXT,to_user TEXT,text TEXT,timestamp TEXT)')
            connection.execute("INSERT INTO messages VALUES(1,'alice','bob','keep me','old-date')")
        migrations.migrate(self.database,'chat')
        with connect(self.database) as connection:
            self.assertEqual(connection.execute('SELECT text,is_read FROM messages').fetchone(),('keep me',0))

    def test_room_upgrade_preserves_existing_history_and_presence(self):
        chat=Path(self.folder.name)/'chat.db'
        steps={kind:items[:-1] for kind,items in migrations.MIGRATIONS.items()}
        with patch.dict(migrations.MIGRATIONS,steps):
            migrations.migrate(self.database,'users')
            migrations.migrate(chat,'chat')
        with connect(self.database) as c:
            c.execute("INSERT INTO channels(id,code,name,owner_login) VALUES(1,'old','Space','alice')")
            c.execute("INSERT INTO channel_voice_presence(channel_id,login) VALUES(1,'alice')")
        with connect(chat) as c:
            c.execute("INSERT INTO channel_messages(channel_id,from_user,text) VALUES(1,'alice','keep history')")
        migrations.migrate(self.database,'users')
        migrations.migrate(chat,'chat')
        with connect(self.database) as c:
            self.assertEqual(c.execute('SELECT id,kind FROM channel_rooms ORDER BY id').fetchall(),[(0,'text'),(1,'voice')])
            self.assertEqual(c.execute('SELECT login,room_id FROM channel_voice_presence').fetchone(),('alice',1))
        with connect(chat) as c:
            self.assertEqual(c.execute('SELECT text,room_id FROM channel_messages').fetchone(),('keep history',0))
