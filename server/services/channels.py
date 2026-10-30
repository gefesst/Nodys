"""Channel membership, roles, presence and settings; no socket or UI dependencies."""
import datetime as dt
import secrets
import sqlite3
import string
from typing import Any, Dict, List, Optional, Tuple
try:
    from ..storage.database import connect as database_connection
    from ..domain.authorization import channel_voice_allowed
    from ..domain.presence_order import accept_update
except ImportError:
    from storage.database import connect as database_connection
    from domain.authorization import channel_voice_allowed
    from domain.presence_order import accept_update

_VALID_CHANNEL_ROLES = {"member", "moderator", "admin"}
_VALID_MIN_ACCESS_ROLES = {"member", "moderator", "admin"}
_ROLE_RANK = {"member": 1, "moderator": 2, "admin": 3, "owner": 4}
VOICE_PRESENCE_TTL_SEC = 8


class ChannelService:
    def __init__(self, database, chat_database, now, iso, online_seconds=45):
        self.database = database
        self.chat_database = chat_database
        self.now = now
        self.iso = iso
        self.online_seconds = online_seconds

    def valid_room(self, channel_id, room_id, kind):
        with database_connection(self.database) as conn:
            return bool(conn.execute("SELECT 1 FROM channel_rooms WHERE channel_id=? AND id=? AND kind=?",(channel_id,room_id,kind)).fetchone())

    def list_rooms(self, login, channel_id):
        with database_connection(self.database) as conn:
            conn.row_factory=sqlite3.Row
            role=self._channel_member_role(conn,channel_id,login)
            if not role:raise ValueError('Нет доступа к пространству')
            self._cleanup_channel_voice_presence(conn,channel_id)
            rows=[dict(r) for r in conn.execute("SELECT id,kind,name FROM channel_rooms WHERE channel_id=? ORDER BY id",(channel_id,))]
            for room in rows:
                room['participants']=[dict(r) for r in conn.execute("SELECT p.login,COALESCE(u.nickname,p.login) AS nickname,COALESCE(u.avatar,'') AS avatar,p.speaking FROM channel_voice_presence p LEFT JOIN users u ON u.login=p.login WHERE p.channel_id=? AND p.room_id=? ORDER BY p.login",(channel_id,room['id']))] if room['kind']=='voice' else []
            return dict(rooms=rows,can_manage=role in ('owner','admin'))

    def edit_room(self, login, channel_id, name, kind=None, room_id=None):
        name=(name or '').strip()
        if not name or len(name)>64 or any(ord(c)<32 for c in name):raise ValueError('Название: от 1 до 64 символов')
        with database_connection(self.database) as conn:
            if not conn.in_transaction:conn.execute('BEGIN IMMEDIATE')
            if self._channel_member_role(conn,channel_id,login) not in ('owner','admin'):raise ValueError('Управлять каналами могут владелец и администраторы')
            if room_id is None:
                if kind not in ('text','voice'):raise ValueError('Выберите тип канала')
                count,maximum=conn.execute('SELECT COUNT(*),MAX(id) FROM channel_rooms WHERE channel_id=?',(channel_id,)).fetchone()
                if count>=100:raise ValueError('Не более 100 каналов в пространстве')
                room_id=(maximum if maximum is not None else 1)+1
                conn.execute('INSERT INTO channel_rooms(channel_id,id,kind,name) VALUES(?,?,?,?)',(channel_id,room_id,kind,name))
            else:
                if not conn.execute('UPDATE channel_rooms SET name=? WHERE channel_id=? AND id=?',(name,channel_id,room_id)).rowcount:raise ValueError('Канал не найден')
            return room_id

    def _generate_channel_code(self, conn: sqlite3.Connection, length: int = 8) -> str:
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(20):
            code = ''.join(secrets.choice(alphabet) for _ in range(length))
            row = conn.execute("SELECT 1 FROM channels WHERE code=?", (code,)).fetchone()
            if not row:
                return code
        # ultra-rare fallback
        return ''.join(secrets.choice(alphabet) for _ in range(length + 2))

    def create_channel(self, owner_login: str, name: str, avatar: str = "") -> Dict[str, Any]:
        channel_name = (name or "").strip()
        if not channel_name:
            raise ValueError("Название канала не может быть пустым")
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            code = self._generate_channel_code(conn)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO channels(code, name, avatar, owner_login, text_min_role, voice_min_role, created_at) VALUES(?,?,?,?,?,?,?)",
                (code, channel_name[:64], avatar or "", owner_login, "member", "member", self.iso(self.now())),
            )
            channel_id = int(cur.lastrowid)
            conn.executemany("INSERT INTO channel_rooms(channel_id,id,kind,name) VALUES(?,?,?,?)",[(channel_id,0,"text","основной"),(channel_id,1,"voice","Общий")])
            cur.execute(
                "INSERT OR IGNORE INTO channel_members(channel_id, login, joined_at, role) VALUES(?,?,?,?)",
                (channel_id, owner_login, self.iso(self.now()), "admin"),
            )
            conn.commit()
    
            row = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (channel_id,),
            ).fetchone()
            return dict(row) if row else {
                "id": channel_id,
                "code": code,
                "name": channel_name[:64],
                "avatar": avatar or "",
                "owner_login": owner_login,
            }

    def list_user_channels(self, login: str) -> list:
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            self._cleanup_channel_voice_presence(conn)
            rows = conn.execute(
                """
                SELECT c.id, c.code, c.name, c.avatar, c.owner_login, c.text_min_role, c.voice_min_role, c.created_at,
                       CASE
                           WHEN c.owner_login = m.login THEN 'owner'
                           ELSE COALESCE(NULLIF(m.role,''), 'member')
                       END AS my_role,
                       (SELECT COUNT(*) FROM channel_members cm WHERE cm.channel_id = c.id) AS participants_count,
                       (SELECT COUNT(*) FROM channel_voice_presence vp WHERE vp.channel_id = c.id) AS voice_online_count
                FROM channels c
                JOIN channel_members m ON m.channel_id = c.id
                WHERE m.login=?
                ORDER BY LOWER(c.name) ASC, c.id ASC
                """,
                (login,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_channel_by_id(self, channel_id: int) -> Optional[Dict[str, Any]]:
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (int(channel_id),),
            ).fetchone()
            return dict(row) if row else None

    def is_channel_member(self, channel_id: int, login: str) -> bool:
        with database_connection(self.database, timeout=10) as conn:
            row = conn.execute(
                "SELECT 1 FROM channel_members WHERE channel_id=? AND login=? LIMIT 1",
                (int(channel_id), login),
            ).fetchone()
            return bool(row)

    def join_channel_by_code(self, login: str, code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        code_norm = (code or "").strip().upper()
        if not code_norm:
            return False, "Укажите код канала", None
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE UPPER(code)=?",
                (code_norm,),
            ).fetchone()
            if not row:
                return False, "Канал не найден", None
    
            channel_id = int(row["id"])
            conn.execute(
                "INSERT OR IGNORE INTO channel_members(channel_id, login, joined_at, role) VALUES(?,?,?,?)",
                (channel_id, login, self.iso(self.now()), "member"),
            )
            conn.commit()
            return True, "ok", dict(row)

    def send_channel_invite(self, actor_login: str, channel_id: int, target_login: str) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        to_login = (target_login or "").strip()
        if cid <= 0 or not to_login:
            return False, "Некорректные данные"
        if actor_login == to_login:
            return False, "Нельзя пригласить самого себя"
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
    
            target_user = conn.execute("SELECT 1 FROM users WHERE login=?", (to_login,)).fetchone()
            if not target_user:
                return False, "Пользователь не найден"
    
            ch, my_role = self._get_channel_and_my_role(conn, cid, actor_login)
            if not ch or not my_role:
                return False, "Нет доступа к каналу"
    
            perms = self._role_permissions(my_role, ch.get("text_min_role", "member"), ch.get("voice_min_role", "member"))
            if not bool(perms.get("can_invite", False)):
                return False, "Недостаточно прав"
    
            already_member = conn.execute(
                "SELECT 1 FROM channel_members WHERE channel_id=? AND login=?",
                (cid, to_login),
            ).fetchone()
            if already_member:
                return False, "Пользователь уже состоит в канале"
    
            existing = conn.execute(
                "SELECT id FROM channel_invites WHERE channel_id=? AND to_user=? AND status='pending' LIMIT 1",
                (cid, to_login),
            ).fetchone()
            if existing:
                return False, "У этого пользователя уже есть активное приглашение"
    
            now = self.iso(self.now())
            conn.execute(
                """
                INSERT INTO channel_invites(channel_id, from_user, to_user, status, created_at, updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (cid, actor_login, to_login, "pending", now, now),
            )
            conn.commit()
        return True, "ok"

    def get_incoming_channel_invites(self, login: str) -> List[Dict[str, Any]]:
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT i.id AS invite_id,
                       i.channel_id,
                       i.from_user,
                       i.to_user,
                       i.created_at,
                       c.name AS channel_name,
                       c.avatar AS channel_avatar,
                       c.code AS channel_code,
                       COALESCE(u.nickname, i.from_user) AS from_nickname,
                       COALESCE(u.avatar, '') AS from_avatar
                FROM channel_invites i
                JOIN channels c ON c.id = i.channel_id
                LEFT JOIN users u ON u.login = i.from_user
                WHERE i.to_user=? AND i.status='pending'
                ORDER BY i.id DESC
                """,
                (login,),
            ).fetchall()
            return [dict(r) for r in rows]

    def respond_channel_invite(self, login: str, invite_id: int, accept: bool) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        iid = int(invite_id or 0)
        if iid <= 0:
            return False, "Некорректное приглашение", None
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            inv = conn.execute(
                "SELECT id, channel_id, to_user, status FROM channel_invites WHERE id=?",
                (iid,),
            ).fetchone()
            if not inv:
                return False, "Приглашение не найдено", None
    
            if inv["to_user"] != login:
                return False, "Это приглашение адресовано другому пользователю", None
    
            if (inv["status"] or "").lower() != "pending":
                return False, "Приглашение уже обработано", None
    
            cid = int(inv["channel_id"])
            ch = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            if not ch:
                now = self.iso(self.now())
                conn.execute(
                    "UPDATE channel_invites SET status='declined', updated_at=? WHERE id=?",
                    (now, iid),
                )
                conn.commit()
                return False, "Канал уже не существует", None
    
            now = self.iso(self.now())
            if accept:
                conn.execute(
                    "INSERT OR IGNORE INTO channel_members(channel_id, login, joined_at, role) VALUES(?,?,?,?)",
                    (cid, login, now, "member"),
                )
                conn.execute(
                    "UPDATE channel_invites SET status='accepted', updated_at=? WHERE channel_id=? AND to_user=? AND status='pending'",
                    (now, cid, login),
                )
                conn.commit()
                return True, "ok", dict(ch)
    
            conn.execute(
                "UPDATE channel_invites SET status='declined', updated_at=? WHERE id=?",
                (now, iid),
            )
            conn.commit()
            return True, "ok", None

    def get_channel_messages(self, channel_id: int, limit: int = 200, room_id=0) -> list:
        lim = max(1, min(500, int(limit or 200)))
        with database_connection(self.chat_database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, channel_id, from_user, text, timestamp AS created_at, attachment_id
                FROM channel_messages
                WHERE channel_id=? AND room_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(channel_id), int(room_id), lim),
            ).fetchall()
            # Возвращаем в хронологическом порядке для UI.
            try:
                from ..storage.attachments import enrich
            except ImportError:
                from storage.attachments import enrich
            return enrich(conn, [dict(r) for r in reversed(rows)])

    def save_channel_message(self, channel_id: int, from_user: str, text: str, client_message_id=None, room_id=0, attachment_id=None):
        msg = (text or "").strip()
        if not msg and not attachment_id:
            return False
        with database_connection(self.chat_database, timeout=10) as conn:
            if client_message_id:
                previous = conn.execute('SELECT id,channel_id,text,room_id,attachment_id FROM channel_messages WHERE from_user=? AND client_message_id=?', (from_user,client_message_id)).fetchone()
                if previous:
                    if previous[1:] != (int(channel_id),msg,int(room_id),attachment_id):
                        raise ValueError('Идентификатор сообщения уже использован')
                    return previous[0]
            try:
                from ..storage.attachments import bind
            except ImportError:
                from storage.attachments import bind
            bind(conn, attachment_id, from_user, cid=int(channel_id), room=int(room_id))
            cursor = conn.execute('INSERT INTO channel_messages(channel_id,from_user,text,client_message_id,room_id,attachment_id) VALUES(?,?,?,?,?,?)', (int(channel_id),from_user,msg,client_message_id,int(room_id),attachment_id))
            return cursor.lastrowid

    def get_message_page(self, channel_id, limit=80, before_id=None, after_id=None, room_id=0):
        try:
            from ..storage.pagination import page
        except ImportError:
            from storage.pagination import page
        with database_connection(self.chat_database) as conn:
            return page(conn, 'channel_messages', 'channel_id=? AND room_id=?', (int(channel_id),int(room_id)), limit, before_id, after_id)

    def _normalize_member_role(self, role: str) -> str:
        r = (role or "").strip().lower()
        if r not in _VALID_CHANNEL_ROLES:
            return "member"
        return r

    def _normalize_min_access_role(self, role: str) -> str:
        r = (role or "").strip().lower()
        if r not in _VALID_MIN_ACCESS_ROLES:
            return "member"
        return r

    def _has_min_role(self, user_role: str, min_role: str) -> bool:
        ur = (user_role or "member").strip().lower()
        mr = self._normalize_min_access_role(min_role)
        return _ROLE_RANK.get(ur, 0) >= _ROLE_RANK.get(mr, 1)

    def _channel_member_role(self, conn: sqlite3.Connection, channel_id: int, login: str) -> Optional[str]:
        row = conn.execute(
            "SELECT c.owner_login, m.role FROM channels c LEFT JOIN channel_members m ON m.channel_id=c.id AND m.login=? WHERE c.id=?",
            (login, int(channel_id)),
        ).fetchone()
        if not row:
            return None
        owner = row[0]
        if owner == login:
            return "owner"
        role = row[1] if len(row) > 1 else None
        return self._normalize_member_role(role) if role is not None else None

    def _role_permissions(self, role: str, text_min_role: str = "member", voice_min_role: str = "member") -> Dict[str, bool]:
        rr = (role or "member").strip().lower()
        text_req = self._normalize_min_access_role(text_min_role)
        voice_req = self._normalize_min_access_role(voice_min_role)
    
        can_send_text = self._has_min_role(rr, text_req)
        can_join_voice = self._has_min_role(rr, voice_req)
    
        if rr == "owner":
            return {
                "can_send_text": True,
                "can_join_voice": True,
                "can_invite": True,
                "manage_members": True,
                "manage_channel": True,
                "assign_roles": True,
                "delete_channel": True,
                "text_min_role": text_req,
                "voice_min_role": voice_req,
                "my_role": rr,
            }
        if rr == "admin":
            return {
                "can_send_text": can_send_text,
                "can_join_voice": can_join_voice,
                "can_invite": True,
                "manage_members": True,
                "manage_channel": False,
                "assign_roles": True,
                "delete_channel": False,
                "text_min_role": text_req,
                "voice_min_role": voice_req,
                "my_role": rr,
            }
        if rr == "moderator":
            return {
                "can_send_text": can_send_text,
                "can_join_voice": can_join_voice,
                "can_invite": True,
                "manage_members": True,
                "manage_channel": False,
                "assign_roles": False,
                "delete_channel": False,
                "text_min_role": text_req,
                "voice_min_role": voice_req,
                "my_role": rr,
            }
        return {
            "can_send_text": can_send_text,
            "can_join_voice": can_join_voice,
            "can_invite": True,
            "manage_members": False,
            "manage_channel": False,
            "assign_roles": False,
            "delete_channel": False,
            "text_min_role": text_req,
            "voice_min_role": voice_req,
            "my_role": rr,
        }

    def _channel_online_map(self, conn: sqlite3.Connection) -> Dict[str, bool]:
        now = self.now()
        threshold = now - dt.timedelta(seconds=self.online_seconds)
        rows = conn.execute(
            "SELECT DISTINCT login FROM sessions WHERE last_seen >= ? AND expires_at > ?",
            (self.iso(threshold), self.iso(now)),
        ).fetchall()
        out = {}
        for r in rows:
            try:
                out[r[0]] = True
            except Exception:
                pass
        return out

    def _channel_members_details(self, conn: sqlite3.Connection, channel_id: int, owner_login: str) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT m.login, COALESCE(NULLIF(m.role,''), 'member') AS role,
                   COALESCE(u.nickname, m.login) AS nickname, COALESCE(u.avatar, '') AS avatar
            FROM channel_members m
            LEFT JOIN users u ON u.login = m.login
            WHERE m.channel_id = ?
            ORDER BY CASE WHEN m.login = ? THEN 0 ELSE 1 END, LOWER(COALESCE(u.nickname, m.login)) ASC, LOWER(m.login) ASC
            """,
            (int(channel_id), owner_login),
        ).fetchall()
    
        online_map = self._channel_online_map(conn)
        members = []
        for r in rows:
            login = r[0]
            role = "owner" if login == owner_login else self._normalize_member_role(r[1])
            members.append({
                "login": login,
                "nickname": r[2] or login,
                "avatar": r[3] or "",
                "role": role,
                "online": bool(online_map.get(login)),
            })
        return members

    def _get_channel_and_my_role(self, conn: sqlite3.Connection, channel_id: int, login: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (int(channel_id),),
        ).fetchone()
        if not row:
            return None, None
        ch = dict(row)
        member = conn.execute(
            "SELECT role FROM channel_members WHERE channel_id=? AND login=?",
            (int(channel_id), login),
        ).fetchone()
        if not member:
            return ch, None
        my_role = "owner" if ch.get("owner_login") == login else self._normalize_member_role(member[0] if member else "member")
        return ch, my_role

    def _can_send_text(self, conn: sqlite3.Connection, channel_id: int, login: str) -> bool:
        ch, my_role = self._get_channel_and_my_role(conn, channel_id, login)
        if not ch or not my_role:
            return False
        need = ch.get("text_min_role", "member")
        return self._has_min_role(my_role, need)

    def _can_join_voice(self, conn: sqlite3.Connection, channel_id: int, login: str) -> bool:
        return channel_voice_allowed(conn, login, channel_id)

    def _cleanup_channel_voice_presence(self, conn: sqlite3.Connection, channel_id: Optional[int] = None) -> None:
        threshold = self.iso(self.now() - dt.timedelta(seconds=VOICE_PRESENCE_TTL_SEC))
        if channel_id is None:
            conn.execute("DELETE FROM channel_voice_presence WHERE last_seen < ?", (threshold,))
        else:
            conn.execute(
                "DELETE FROM channel_voice_presence WHERE channel_id=? AND last_seen < ?",
                (int(channel_id), threshold),
            )

    def set_channel_voice_presence(self, login: str, channel_id: int, speaking: bool = False, joined: bool = True, token: str = "", sequence=None, room_id=1) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал"
    
        with database_connection(self.database, timeout=10) as conn:
            if not self.is_channel_member(cid, login):
                return False, "Нет доступа к каналу"
            if not self.valid_room(cid,room_id,"voice"):
                return False,"Голосовой канал не найден"
            if joined and not self._can_join_voice(conn, cid, login):
                return False, "У вас нет прав для входа в голосовой канал"
    
            conn.execute("BEGIN IMMEDIATE")
            if not accept_update(conn, token, cid, sequence):
                return True, "Устаревшее обновление пропущено"
            self._cleanup_channel_voice_presence(conn, cid)
            if not joined:
                conn.execute(
                    "DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?",
                    (cid, login),
                )
                conn.commit()
                return True, "ok"
    
            conn.execute(
                """
                INSERT INTO channel_voice_presence(channel_id, login, speaking, last_seen, room_id)
                VALUES(?,?,?,?,?)
                ON CONFLICT(channel_id, login) DO UPDATE SET
                    room_id=excluded.room_id,
                    speaking=excluded.speaking,
                    last_seen=excluded.last_seen
                """,
                (cid, login, 1 if bool(speaking) else 0, self.iso(self.now()),int(room_id)),
            )
            conn.commit()
        return True, "ok"

    def leave_channel_voice(self, login: str, channel_id: int, token: str = "", sequence=None) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал"
        with database_connection(self.database, timeout=10) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not accept_update(conn, token, cid, sequence):
                return True, "Устаревшее обновление пропущено"
            conn.execute(
                "DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?",
                (cid, login),
            )
            conn.commit()
        return True, "ok"

    def get_channel_voice_participants(self, channel_id: int, login: str, room_id=1) -> Tuple[bool, str, List[Dict[str, Any]]]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал", []
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            if not self.is_channel_member(cid, login):
                return False, "Нет доступа к каналу", []
            # visibility is available to all channel members
            self._cleanup_channel_voice_presence(conn, cid)
    
            ch = conn.execute(
                "SELECT owner_login FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            if not ch:
                return False, "Канал не найден", []
    
            owner_login = ch["owner_login"]
            rows = conn.execute(
                """
                SELECT p.login,
                       p.speaking,
                       p.last_seen,
                       COALESCE(u.nickname, p.login) AS nickname,
                       COALESCE(u.avatar, '') AS avatar,
                       COALESCE(NULLIF(m.role,''), 'member') AS role
                FROM channel_voice_presence p
                LEFT JOIN users u ON u.login = p.login
                LEFT JOIN channel_members m ON m.channel_id = p.channel_id AND m.login = p.login
                WHERE p.channel_id=? AND p.room_id=?
                ORDER BY p.speaking DESC, LOWER(COALESCE(u.nickname, p.login)) ASC, LOWER(p.login) ASC
                """,
                (cid,int(room_id)),
            ).fetchall()
    
            online_map = self._channel_online_map(conn)
    
            out: List[Dict[str, Any]] = []
            for r in rows:
                lg = r["login"]
                role = "owner" if lg == owner_login else self._normalize_member_role(r["role"])
                out.append({
                    "login": lg,
                    "nickname": r["nickname"] or lg,
                    "avatar": r["avatar"] or "",
                    "role": role,
                    "speaking": bool(int(r["speaking"] or 0)),
                    "online": bool(online_map.get(lg)),
                })
    
            return True, "ok", out

    def get_channel_details_for_user(self, channel_id: int, login: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал", None
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            if not row:
                return False, "Канал не найден", None
    
            member = conn.execute(
                "SELECT role FROM channel_members WHERE channel_id=? AND login=?",
                (cid, login),
            ).fetchone()
            if not member:
                return False, "Нет доступа к каналу", None
    
            ch = dict(row)
            my_role = "owner" if ch.get("owner_login") == login else self._normalize_member_role(member[0] if member else "member")
            perms = self._role_permissions(my_role, ch.get("text_min_role", "member"), ch.get("voice_min_role", "member"))
            members = self._channel_members_details(conn, cid, ch.get("owner_login") or "")
    
            result = {
                "channel": ch,
                "my_role": my_role,
                "permissions": perms,
                "members": members,
            }
            return True, "ok", result

    def update_channel_settings(self, actor_login: str, channel_id: int, name: str, avatar: str, text_min_role: str = "member", voice_min_role: str = "member") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал", None
    
        new_name = (name or "").strip()
        if not new_name:
            return False, "Введите название канала", None
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            ch = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            if not ch:
                return False, "Канал не найден", None
    
            if ch["owner_login"] != actor_login:
                return False, "Недостаточно прав", None
    
            text_policy = self._normalize_min_access_role(text_min_role)
            voice_policy = self._normalize_min_access_role(voice_min_role)
            conn.execute(
                "UPDATE channels SET name=?, avatar=?, text_min_role=?, voice_min_role=? WHERE id=?",
                (new_name[:64], avatar or "", text_policy, voice_policy, cid),
            )
            conn.commit()
    
            out = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            return True, "ok", dict(out) if out else None

    def regenerate_channel_code(self, actor_login: str, channel_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал", None
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            ch = conn.execute(
                "SELECT id, owner_login FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            if not ch:
                return False, "Канал не найден", None
            if ch["owner_login"] != actor_login:
                return False, "Недостаточно прав", None
    
            code = self._generate_channel_code(conn)
            conn.execute("UPDATE channels SET code=? WHERE id=?", (code, cid))
            conn.commit()
    
            out = conn.execute(
                "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
                (cid,),
            ).fetchone()
            return True, "ok", dict(out) if out else None

    def set_channel_member_role(self, actor_login: str, channel_id: int, target_login: str, role: str) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        tgt = (target_login or "").strip()
        if role not in _VALID_CHANNEL_ROLES:
            return False, "Некорректная роль"
        new_role = role
    
        if cid <= 0 or not tgt:
            return False, "Некорректные данные"
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
            if not ch:
                return False, "Канал не найден"
    
            owner = ch["owner_login"]
            actor_role = self._channel_member_role(conn, cid, actor_login)
            if actor_role not in {"owner", "admin"}:
                return False, "Недостаточно прав"
    
            tgt_member = conn.execute(
                "SELECT login, COALESCE(NULLIF(role,''), 'member') FROM channel_members WHERE channel_id=? AND login=?",
                (cid, tgt),
            ).fetchone()
            if not tgt_member:
                return False, "Участник не найден"
    
            if tgt == owner:
                return False, "Нельзя изменить роль владельца"
    
            if new_role == "owner":
                return False, "Нельзя назначить владельца через эту операцию"
    
            tgt_role = "owner" if tgt == owner else self._normalize_member_role(tgt_member[1])
            if actor_role == "admin":
                if tgt_role in {"owner", "admin"}:
                    return False, "Админ не может изменить роль этого участника"
                if new_role == "admin":
                    return False, "Админ не может назначать администраторов"
    
            conn.execute(
                "UPDATE channel_members SET role=? WHERE channel_id=? AND login=?",
                (new_role, cid, tgt),
            )
            conn.commit()
            return True, "ok"

    def remove_channel_member(self, actor_login: str, channel_id: int, target_login: str) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        tgt = (target_login or "").strip()
        if cid <= 0 or not tgt:
            return False, "Некорректные данные"
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
            if not ch:
                return False, "Канал не найден"
    
            owner = ch["owner_login"]
            actor_role = self._channel_member_role(conn, cid, actor_login)
            if actor_role not in {"owner", "admin", "moderator"}:
                return False, "Недостаточно прав"
    
            tgt_member = conn.execute(
                "SELECT login, COALESCE(NULLIF(role,''), 'member') FROM channel_members WHERE channel_id=? AND login=?",
                (cid, tgt),
            ).fetchone()
            if not tgt_member:
                return False, "Участник не найден"
    
            if tgt == owner:
                return False, "Нельзя удалить владельца"
    
            tgt_role = self._normalize_member_role(tgt_member[1])
            if actor_role == "admin" and tgt_role == "admin":
                return False, "Админ не может удалить другого админа"
            if actor_role == "moderator" and tgt_role != "member":
                return False, "Модератор может удалять только обычных участников"
    
            conn.execute("DELETE FROM channel_members WHERE channel_id=? AND login=?", (cid, tgt))
            conn.execute("DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?", (cid, tgt))
            conn.execute(
                "DELETE FROM channel_invites WHERE channel_id=? AND (from_user=? OR to_user=?)",
                (cid, tgt, tgt),
            )
            conn.commit()
            return True, "ok"

    def leave_channel(self, login: str, channel_id: int) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал"
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
            if not ch:
                return False, "Канал не найден"
    
            if ch["owner_login"] == login:
                return False, "Владелец не может выйти из канала. Передайте владельца или удалите канал"
    
            row = conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND login=?", (cid, login)).fetchone()
            if not row:
                return False, "Вы не участник канала"
    
            conn.execute("DELETE FROM channel_members WHERE channel_id=? AND login=?", (cid, login))
            conn.execute("DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?", (cid, login))
            conn.execute(
                "DELETE FROM channel_invites WHERE channel_id=? AND (from_user=? OR to_user=?)",
                (cid, login, login),
            )
            conn.commit()
            return True, "ok"

    def delete_channel(self, actor_login: str, channel_id: int) -> Tuple[bool, str]:
        cid = int(channel_id or 0)
        if cid <= 0:
            return False, "Не указан канал"
    
        with database_connection(self.database, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
            if not ch:
                return False, "Канал не найден"
    
            if ch["owner_login"] != actor_login:
                return False, "Только владелец может удалить канал"
    
            conn.execute("DELETE FROM channel_members WHERE channel_id=?", (cid,))
            conn.execute("DELETE FROM channel_voice_presence WHERE channel_id=?", (cid,))
            conn.execute("DELETE FROM channel_invites WHERE channel_id=?", (cid,))
            conn.execute("INSERT OR IGNORE INTO channel_cleanup VALUES(?)", (cid,))
            conn.execute("DELETE FROM voice_presence_versions WHERE channel_id=?", (cid,))
            conn.execute("DELETE FROM voice_tickets WHERE room=? OR room LIKE ?", (f"channel:{cid}",f"channel:{cid}:%"))
            conn.execute("DELETE FROM channel_rooms WHERE channel_id=?", (cid,))
            conn.execute("DELETE FROM channels WHERE id=?", (cid,))
            conn.commit()
    
        return True, "ok"
