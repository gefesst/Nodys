"""Transactional call state and durable notifications; SQLite is authoritative."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
try:
    from ..storage.database import connect
    from ..storage import events
except ImportError:
    from storage.database import connect
    from storage import events


def now():
    return datetime.now(timezone.utc)


class CallService:
    def __init__(self, database, publish_legacy, stale_seconds=25, online_seconds=45):
        self.database = database
        self.publish_legacy = publish_legacy
        self.stale_seconds = stale_seconds
        self.online_seconds = online_seconds

    @contextmanager
    def transaction(self):
        notifications = []
        with connect(self.database, timeout=10) as connection:
            connection.execute('BEGIN IMMEDIATE')
            yield connection, notifications
        # Legacy in-memory delivery is secondary and only happens after commit.
        for login, event in notifications:
            self.publish_legacy(login, event)

    def emit(self, connection, notifications, login, event):
        event = dict(event, ts=now().isoformat())
        events.append(connection, login, event)
        notifications.append((login, event))

    def start(self, caller, callee):
        with self.transaction() as (connection, notifications):
            if caller == callee or not connection.execute('SELECT 1 FROM users WHERE login=?',(callee,)).fetchone():
                return False, 'Пользователь не найден'
            if not connection.execute('SELECT 1 FROM friends WHERE user_login=? AND friend_login=?',(caller,callee)).fetchone():
                return False, 'Можно звонить только друзьям'
            stamp = now()
            if not connection.execute('SELECT 1 FROM sessions WHERE login=? AND expires_at>? AND last_seen>=?',
                    (callee,stamp.isoformat(),(stamp-timedelta(seconds=self.online_seconds)).isoformat())).fetchone():
                return False, 'Пользователь не в сети'
            if connection.execute('SELECT 1 FROM active_call_pairs WHERE user_a IN (?,?) OR user_b IN (?,?)',
                                  (caller,callee,caller,callee)).fetchone():
                return False, 'Пользователь занят'
            a,b = sorted((caller,callee))
            connection.execute('''INSERT INTO active_call_pairs
                (user_a,user_b,status,created_at,updated_at,caller_login,seen_a,seen_b)
                VALUES(?,?,'ringing',?,?,?,?,?)''',(a,b,stamp.isoformat(),stamp.isoformat(),caller,stamp.isoformat(),stamp.isoformat()))
            self.emit(connection,notifications,callee,dict(type='incoming_call',from_user=caller))
        return True, 'ok'

    def accept(self, callee, caller):
        a,b=sorted((callee,caller))
        with self.transaction() as (connection, notifications):
            row=connection.execute('SELECT status,caller_login FROM active_call_pairs WHERE user_a=? AND user_b=?',(a,b)).fetchone()
            if not row or row[1] != caller or caller == callee:
                return False
            if row[0] == 'active':
                return True
            if row[0] != 'ringing':
                return False
            stamp=now().isoformat()
            connection.execute("UPDATE active_call_pairs SET status='active',updated_at=?,seen_a=?,seen_b=? WHERE user_a=? AND user_b=?",
                               (stamp,stamp,stamp,a,b))
            self.emit(connection,notifications,caller,dict(type='call_accepted',by_user=callee,with_user=callee))
            self.emit(connection,notifications,callee,dict(type='call_started',with_user=caller))
        return True

    def finish(self, user, peer=None, decline=False, expected_id=None):
        with self.transaction() as (connection, notifications):
            row=connection.execute('SELECT user_a,user_b,status,caller_login,created_at FROM active_call_pairs WHERE user_a=? OR user_b=?',(user,user)).fetchone()
            if not row:
                return False
            if expected_id is not None and row[4] != expected_id:
                return False
            other=row[1] if row[0] == user else row[0]
            if peer is not None and other != peer:
                return False
            if decline and (row[2] != 'ringing' or row[3] != other):
                return False
            connection.execute('DELETE FROM active_call_pairs WHERE user_a=? AND user_b=?',row[:2])
            for recipient, counterpart in ((user,other),(other,user)):
                event=dict(type='call_declined' if decline else 'call_ended',with_user=counterpart,by_user=user)
                self.emit(connection,notifications,recipient,event)
        return True

    def touch(self, user):
        stamp=now().isoformat()
        with connect(self.database, timeout=10) as connection:
            connection.execute('UPDATE active_call_pairs SET seen_a=? WHERE user_a=?',(stamp,user))
            connection.execute('UPDATE active_call_pairs SET seen_b=? WHERE user_b=?',(stamp,user))

    def prune(self):
        threshold=(now()-timedelta(seconds=self.stale_seconds)).isoformat()
        # Avoid taking a write lock when there is nothing to expire.
        with connect(self.database, timeout=10) as connection:
            if not connection.execute('SELECT 1 FROM active_call_pairs WHERE seen_a<? OR seen_b<? LIMIT 1',(threshold,threshold)).fetchone():
                return
        with self.transaction() as (connection, notifications):
            rows=connection.execute('SELECT user_a,user_b FROM active_call_pairs WHERE seen_a<? OR seen_b<?',(threshold,threshold)).fetchall()
            for a,b in rows:
                connection.execute('DELETE FROM active_call_pairs WHERE user_a=? AND user_b=?',(a,b))
                for user,peer in ((a,b),(b,a)):
                    self.emit(connection,notifications,user,dict(type='call_ended',with_user=peer,by_user='system'))
