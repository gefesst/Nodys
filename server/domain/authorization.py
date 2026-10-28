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


def channel_id(room):
    raw = str(room).strip().lower().removeprefix('channel:')
    return int(raw) if raw.isascii() and raw.isdigit() and int(raw) > 0 else None


def channel_voice_allowed(connection, login, room):
    cid = channel_id(room)
    if cid is None:
        return False
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
