"""Short-lived scoped voice credentials and one-process key claims."""
import secrets
import time
try:
    from ..domain.authorization import session_valid, channel_voice_allowed, private_call_allowed, channel_id, canonical_room
except ImportError:
    from domain.authorization import session_valid, channel_voice_allowed, private_call_allowed, channel_id, canonical_room

LIFETIME = 3600


def initialize(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS voice_tickets (
        id BLOB PRIMARY KEY, login TEXT NOT NULL, token TEXT NOT NULL,
        room TEXT, peer TEXT, client_key BLOB NOT NULL, server_key BLOB NOT NULL,
        expires REAL NOT NULL, claimed TEXT NOT NULL DEFAULT '')''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_voice_tickets_token ON voice_tickets(token)')
    connection.execute('DELETE FROM voice_tickets WHERE expires<=? OR token NOT IN (SELECT token FROM sessions)', (time.time(),))


def allowed(connection, ticket):
    return (ticket['expires'] > time.time()
            and session_valid(connection, ticket['login'], ticket['token'])
            and (channel_voice_allowed(connection, ticket['login'], ticket['room'])
                 if ticket['room'] else private_call_allowed(connection, ticket['login'], ticket['peer'])))


def issue(connection, login, token, room=None, peer=None):
    if bool(room) == bool(peer) or (peer is not None and not isinstance(peer, str)):
        raise ValueError('Укажите один голосовой канал или собеседника')
    cid = channel_id(room) if room else None
    if room and cid is None:
        raise ValueError('Некорректный канал')
    ticket = dict(id=secrets.token_bytes(16), login=login, token=token,
                  room=canonical_room(room) if cid else None, peer=peer,
                  client_key=secrets.token_bytes(32), server_key=secrets.token_bytes(32),
                  expires=time.time()+LIFETIME)
    if not allowed(connection, ticket):
        raise ValueError('Нет доступа к голосовому соединению')
    # One voice transport per authentication session; reconnect revokes old keys.
    connection.execute('DELETE FROM voice_tickets WHERE token=? OR expires<=?', (token, time.time()))
    connection.execute('''INSERT INTO voice_tickets
        (id,login,token,room,peer,client_key,server_key,expires) VALUES(?,?,?,?,?,?,?,?)''',
        tuple(ticket[key] for key in ('id','login','token','room','peer','client_key','server_key','expires')))
    return {key: ticket[key].hex() for key in ('id','client_key','server_key')} | {'expires':ticket['expires']}


def read(connection, identity):
    cursor = connection.execute('SELECT * FROM voice_tickets WHERE id=?', (identity,))
    row = cursor.fetchone()
    return dict(zip((col[0] for col in cursor.description), row)) if row else None


def claim(connection, identity, process_id):
    result = connection.execute("UPDATE voice_tickets SET claimed=? WHERE id=? AND claimed=''",
                                (process_id, identity))
    return result.rowcount == 1
