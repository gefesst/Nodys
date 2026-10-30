"""Ephemeral, session-scoped, client-reported activity; never proof of Steam ownership."""
import datetime as dt
import time
from .database import connect

TTL = 45


def initialize(c):
    c.execute('''CREATE TABLE steam_activity (
        token TEXT PRIMARY KEY REFERENCES sessions(token) ON DELETE CASCADE,
        sequence INTEGER NOT NULL, nickname TEXT NOT NULL,
        game TEXT NOT NULL, app_id TEXT NOT NULL, updated_at REAL NOT NULL)''')


def publish(database, token, data):
    if 'activity_sequence' not in data:
        return
    with connect(database) as c:
        c.execute('DELETE FROM steam_activity WHERE token NOT IN (SELECT token FROM sessions)')
        if not c.execute('SELECT 1 FROM sessions WHERE token=?', (token,)).fetchone():
            return
        c.execute('''INSERT INTO steam_activity(token,sequence,nickname,game,app_id,updated_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET
            sequence=excluded.sequence,nickname=excluded.nickname,game=excluded.game,
            app_id=excluded.app_id,updated_at=excluded.updated_at
            WHERE excluded.sequence > steam_activity.sequence''',
            (token, data['activity_sequence'], data.get('steam_nickname', ''),
             data.get('steam_game', ''), data.get('steam_app_id', ''), time.time()))


def enrich(database, people):
    """Only enrich already authorized lists. No public account/activity lookup."""
    now = dt.datetime.now(dt.timezone.utc)
    with connect(database) as c:
        rows = c.execute('''SELECT s.login,a.nickname,a.game,a.app_id,a.updated_at
            FROM steam_activity a JOIN sessions s ON s.token=a.token
            WHERE a.updated_at>? AND s.expires_at>? AND s.last_seen>?
            ORDER BY a.updated_at''', (time.time()-TTL, now.isoformat(), (now-dt.timedelta(seconds=TTL)).isoformat())).fetchall()
    latest = {r[0]: dict(nickname=r[1], game=r[2], app_id=r[3]) for r in rows}
    for person in people:
        activity = latest.get(person.get('login'))
        person['steam_activity'] = activity if activity and activity['nickname'] else None
    return people


def clear(database, token):
    with connect(database) as c:
        c.execute("UPDATE steam_activity SET nickname='',game='',app_id='',updated_at=0,sequence=? WHERE token=?", (time.time_ns()//1000,token))
