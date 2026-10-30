"""Bounded idempotency receipts and serialized authorization for mutations."""
import hashlib
import json
import time
try:
    from ..storage.database import unit_of_work
    from ..domain.authorization import session_valid
except ImportError:
    from storage.database import unit_of_work
    from domain.authorization import session_valid

CHAT_ACTIONS = {'edit_message', 'delete_message', 'send_message', 'send_channel_message'}
USER_ACTIONS = {'create_channel_room','rename_channel_room','delete_channel','update_profile','create_channel','join_channel','send_channel_invite','respond_channel_invite',
                'update_channel_settings','regenerate_channel_code','set_channel_member_role',
                'remove_channel_member','leave_channel','send_friend_request',
                'accept_friend_request','decline_friend_request'}
ACTIONS = CHAT_ACTIONS | USER_ACTIONS


def initialize(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS mutation_receipts (
        token TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
        response TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(token,request_id))''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_mutation_receipts_created ON mutation_receipts(created)')


class _Rejected(Exception):
    def __init__(self, result):
        self.result = result


def execute(users_db, chat_db, request, operation):
    try:
        return _execute(users_db, chat_db, request, operation)
    except _Rejected as error:
        return error.result


def _execute(users_db, chat_db, request, operation):
    # Always take users before chat: ACL changes cannot race a message insertion.
    with unit_of_work(users_db) as accounts:
        token = request.get('token') or request.get('session_token') or ''
        owner = accounts.execute('SELECT login FROM sessions WHERE token=?',(token,)).fetchone()
        if not owner or not session_valid(accounts, owner[0], token):
            raise _Rejected({'status':'error','code':'session_invalid','message':'Сессия недействительна'})
        target = chat_db if request['action'] in CHAT_ACTIONS else users_db
        with unit_of_work(target) as connection:
            identity = request.get('request_id')
            token = request.get('token') or request.get('session_token') or ''
            digest = hashlib.sha256(json.dumps({k:v for k,v in request.items() if k != 'request_id'},
                        sort_keys=True,ensure_ascii=True).encode()).hexdigest()
            if identity:
                row = connection.execute('SELECT digest,response FROM mutation_receipts WHERE token=? AND request_id=?',
                                         (token,identity)).fetchone()
                if row:
                    if row[0] != digest:
                        return {'status':'error','code':'request_conflict','message':'Идентификатор запроса уже использован'}
                    return json.loads(row[1])
            result = operation()
            if result.get("status") != "ok":
                raise _Rejected(result)
            if identity and result.get('status') == 'ok':
                connection.execute('DELETE FROM mutation_receipts WHERE created<?',(time.time()-86400,))
                connection.execute('INSERT INTO mutation_receipts VALUES(?,?,?,?,?)',
                    (token,identity,digest,json.dumps(result,ensure_ascii=True),time.time()))
                connection.execute('''DELETE FROM mutation_receipts WHERE token=? AND request_id NOT IN
                    (SELECT request_id FROM mutation_receipts WHERE token=? ORDER BY created DESC LIMIT 1000)''',(token,token))
            return result
