"""Durable, non-destructive per-user events with bounded retention."""
import json
import time


def initialize(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS user_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL,
        payload TEXT NOT NULL, created_at REAL NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_user_events_login_id ON user_events(login,id)')


def append(connection, login, event):
    connection.execute('INSERT INTO user_events(login,payload,created_at) VALUES(?,?,?)',
                       (login,json.dumps(event,ensure_ascii=False),time.time()))
    connection.execute('DELETE FROM user_events WHERE created_at < ?', (time.time()-180,))
    connection.execute('''DELETE FROM user_events WHERE login=? AND id NOT IN
        (SELECT id FROM user_events WHERE login=? ORDER BY id DESC LIMIT 200)''',(login,login))


def read(connection, login, after):
    if type(after) is not int or not 0 <= after <= 9223372036854775807:
        raise ValueError('Некорректный курсор событий')
    rows = connection.execute('''SELECT id,payload FROM user_events
        WHERE login=? AND id>? AND created_at>=? ORDER BY id LIMIT 200''',
        (login,after,time.time()-180)).fetchall()
    return [dict(json.loads(payload),event_id=event_id) for event_id,payload in rows]
