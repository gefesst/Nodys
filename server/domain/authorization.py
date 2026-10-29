"""Fail-closed authorization shared by server transports."""
from datetime import datetime, timezone

ROLE_RANK = {'member': 1, 'moderator': 2, 'admin': 3, 'owner': 4}


def session_valid(connection, login, token):
    row = connection.execute('SELECT expires_at FROM sessions WHERE login=? AND token=?', (login, token)).fetchone()
    if not row:
        return False
    try:
        expires = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return False


def voice_scope(room):
    raw=str(room).strip().lower().removeprefix('channel:')
    parts=raw.split(':')
    if len(parts) not in (1,2) or any(not p.isascii() or not p.isdigit() for p in parts):return None
    cid=int(parts[0]);rid=int(parts[1]) if len(parts)==2 else 1
    return (cid,rid) if cid>0 and rid>0 else None

def channel_id(room):
    scope=voice_scope(room)
    return scope[0] if scope else None

def canonical_room(room):
    scope=voice_scope(room)
    if not scope:return None
    cid,rid=scope
    return f'channel:{cid}' if rid==1 else f'channel:{cid}:{rid}'


def channel_voice_allowed(connection, login, room):
    scope=voice_scope(room)
    if scope is None:return False
    cid,rid=scope
    if not connection.execute("SELECT 1 FROM channel_rooms WHERE channel_id=? AND id=? AND kind='voice'",(cid,rid)).fetchone():return False
    row = connection.execute('''SELECT c.owner_login, c.voice_min_role, m.role
        FROM channels c LEFT JOIN channel_members m ON m.channel_id=c.id AND m.login=?
        WHERE c.id=?''', (login, cid)).fetchone()
    if not row:
        return False
    if row[0] == login:
        return True
    return row[2] in ROLE_RANK and row[1] in ROLE_RANK and ROLE_RANK[row[2]] >= ROLE_RANK[row[1]]


def private_call_allowed(connection, a, b):
    row = connection.execute('SELECT status FROM active_call_pairs WHERE user_a=? AND user_b=?', tuple(sorted((a,b)))).fetchone()
    friend = connection.execute('SELECT 1 FROM friends WHERE user_login=? AND friend_login=?', (a,b)).fetchone()
    return bool(row and row[0] == 'active' and friend)
