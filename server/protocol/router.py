"""Control request adapter over explicit application services; no socket ownership."""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..services.accounts import AccountService
    from ..services.friends import FriendshipService
    from ..services.channels import ChannelService
    from ..services.calls import CallService
    from ..services.events import EventService
    from ..storage.messages import MessageRepository
from typing import Dict, Any
try:
    from .requests import validate as validate_request
    from ..domain.avatars import normalize_avatar
    from ..storage.database import connect as database_connection, unit_of_work
    from ..storage import voice_tickets, steam_activity, events as event_store
except ImportError:
    from protocol.requests import validate as validate_request
    from domain.avatars import normalize_avatar
    from storage.database import connect as database_connection, unit_of_work
    from storage import voice_tickets, steam_activity, events as event_store

@dataclass
class RequestRouter:
    database: str
    accounts: AccountService
    friends: FriendshipService
    messages: MessageRepository
    channels: ChannelService
    calls: CallService
    events: EventService

    def dispatch(self, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            validate_request(data)
        except ValueError as error:
            return {"status":"error", "code":"invalid_request", "message":str(error)}

        action = data.get("action")
        if not action:
            return {"status": "error", "message": "Нет действия"}

        # public actions
        if action == "register":
            login = (data.get("login") or "").strip()
            password = data.get("password") or ""
            nickname = (data.get("nickname") or "").strip()
            try:
                avatar = normalize_avatar(data.get("avatar") or "")
            except ValueError as error:
                return {"status": "error", "message": str(error)}
            if not login or not password or not nickname:
                return {"status": "error", "message": "Заполните все поля"}
            ok = self.accounts.add_user(login, password, nickname, avatar)
            return {"status": "ok"} if ok else {"status": "error", "message": "Логин уже существует"}

        if action == "login":
            login = (data.get("login") or "").strip()
            password = data.get("password") or ""
            with unit_of_work(self.database):
                if not self.accounts.authenticate(login, password):
                    return {"status": "error", "message": "Неверный логин или пароль"}
                info = self.accounts.get_user_info(login) or {"login": login, "nickname": login, "avatar": ""}
                token, expires_at = self.accounts.create_session(login)
            return {
                "status": "ok",
                "login": info["login"],
                "nickname": info["nickname"],
                "avatar": info["avatar"],
                "token": token,
                "expires_at": expires_at,
            }

        if action == "resume_session":
            token = data.get("token") or ""
            sess = self.accounts.get_session_by_token(token)
            if not sess:
                return {"status": "error", "code": "session_invalid", "message": "Сессия недействительна"}
            self.accounts.touch_session(token)
            login = sess["login"]
            info = self.accounts.get_user_info(login) or {"login": login, "nickname": login, "avatar": ""}
            return {
                "status": "ok",
                "login": info["login"],
                "nickname": info["nickname"],
                "avatar": info["avatar"],
                "token": token,
                "expires_at": sess.get("expires_at", ""),
            }

        # Everything below requires auth
        current_user, token, err = self.accounts.require_auth(data)
        if err:
            return err

        if action in {'begin_attachment', 'upload_attachment_chunk', 'download_attachment_chunk'}:
            try:
                from ..storage.attachments import dispatch
            except ImportError:
                from storage.attachments import dispatch
            try:
                return dispatch(self, current_user, data)
            except ValueError as error:
                return dict(status='error', message=str(error))

        if action == "voice_ticket":
            try:
                with database_connection(self.database, timeout=5) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    ticket = voice_tickets.issue(connection, current_user, token,
                                                 data.get("room"), data.get("peer"))
                return {"status": "ok", **ticket}
            except (ValueError, TypeError, OverflowError) as error:
                return {"status": "error", "message": str(error)}

        # Common touch already done

        if action == "find_user":
            target_login = (data.get("target_login") or data.get("login") or "").strip()
            if not target_login:
                return {"status": "error", "message": "Не указан логин пользователя"}
            info = self.accounts.get_user_info(target_login)
            if not info:
                return {"status": "error", "message": "Пользователь не найден"}
            info["online"] = self.accounts.is_online(target_login)
            return {"status": "ok", **info}

        if action == "heartbeat":
            steam_activity.publish(self.database, token, data)
            self.calls.touch(current_user)
            return {"status": "ok"}

        if action == "logout":
            # End active call (if any)
            self.accounts.delete_session(token)
            with database_connection(self.database) as connection:
                remaining = connection.execute('SELECT 1 FROM sessions WHERE login=? AND expires_at>? LIMIT 1',
                                               (current_user, self.accounts.iso(self.accounts.now()))).fetchone()
            if not remaining:
                self.calls.finish(current_user)
            return {"status": "ok"}

        if action == "release_call_state":
            # Used by client on app close to avoid stale "busy" state,
            # but keeps session token valid for auto-login.
            if data.get("call_id"):
                self.calls.finish(current_user, expected_id=data["call_id"])
            return {"status": "ok"}

        if action == "presence_offline":
            # Fast presence convergence on app close while keeping session token.
            steam_activity.clear(self.database, token)
            self.accounts.set_session_offline(token)
            return {"status": "ok"}

        if action == "status":
            # status for the current user only
            return {"status": "ok", "login": current_user, "online": self.accounts.is_online(current_user)}

        if action == "update_profile":
            nickname = (data.get("nickname") or "").strip()
            if not nickname:
                return {"status": "error", "message": "Никнейм не может быть пустым"}
            password = data.get("password") or None
            if password and not self.accounts.authenticate(current_user, data.get("current_password") or ""):
                return {"status":"error", "message":"Укажите верный текущий пароль"}
            try:
                avatar = normalize_avatar(data.get("avatar") or "")
            except ValueError as error:
                return {"status": "error", "message": str(error)}
            self.accounts.update_user_profile(current_user, nickname, password, avatar, keep_token=token)
            return {"status": "ok"}

        # Friends
        if action == "send_friend_request":
            to_user = (data.get("to_user") or "").strip()
            ok = self.friends.send_friend_request(current_user, to_user)
            return {"status": "ok"} if ok else {"status": "error", "message": "Не удалось отправить запрос"}

        if action == "get_friend_requests":
            reqs = self.friends.get_friend_requests(current_user)
            return {"status": "ok", "requests": reqs}

        if action == "accept_friend_request":
            from_user = (data.get("from_user") or "").strip()
            ok = self.friends.accept_friend_request(from_user, current_user)
            return {"status": "ok"} if ok else {"status": "error", "message": "Заявка не найдена или уже обработана"}

        if action == "decline_friend_request":
            from_user = (data.get("from_user") or "").strip()
            ok = self.friends.decline_friend_request(from_user, current_user)
            return {"status": "ok"} if ok else {"status": "error", "message": "Заявка не найдена или уже обработана"}

        if action == "get_friends":
            friends = self.friends.get_friends(current_user)
            friends_info = []
            for f in friends:
                info = self.accounts.get_user_info(f) or {"login": f, "nickname": f, "avatar": ""}
                friends_info.append({
                    "login": info["login"],
                    "nickname": info["nickname"],
                    "avatar": info.get("avatar") or "",
                    "online": self.accounts.is_online(f),
                })
            return {"status": "ok", "friends": steam_activity.enrich(self.database, friends_info)}

        if action == "remove_friend":
            friend_login = (data.get("friend_login") or "").strip()
            if not friend_login:
                return {"status": "error", "message": "Не указан пользователь"}
            ok = self.friends.remove_friend(current_user, friend_login)
            return {"status": "ok"} if ok else {"status": "error", "message": "Друг не найден или уже удалён"}

        # Chat
        if action == "send_message":
            to_user = (data.get("to_user") or "").strip()
            text = (data.get("text") or data.get("message") or "").strip()
            if not to_user or (not text and not data.get('attachment_id')):
                return {"status": "error", "message": "Пустое сообщение"}
            if not self.friends.are_friends(current_user, to_user):
                return {"status":"error", "message":"Отправлять сообщения можно только друзьям"}
            try:
                identity = self.messages.save_message(current_user, to_user, text, data.get('client_message_id'), data.get('attachment_id'))
            except ValueError as error:
                return {'status':'error','code':'request_conflict','message':str(error)}
            return {"status": "ok", "message_id": identity}

        if action == "get_messages":
            # Client usually sends from_user/to_user. We trust session login.
            other = (data.get("to_user") or "").strip()
            if not other or other == current_user:
                other = (data.get("from_user") or "").strip()
            if not other or other == current_user:
                return {"status": "error", "message": "Не указан собеседник"}
            if data.get('paged'):
                try:
                    return dict(status='ok', **self.messages.get_page(current_user, other, data.get('limit',80), data.get('before_id'), data.get('after_id')))
                except ValueError as error:
                    return dict(status='error', message=str(error))
            msgs = self.messages.get_messages(current_user, other, limit=int(data.get("limit", 50) or 50))
            return {"status": "ok", "messages": msgs}

        if action == "mark_chat_read":
            friend = (data.get("friend_login") or "").strip()
            if not friend:
                return {"status": "error", "message": "Не указан собеседник"}
            through=data.get("through_id")
            if through is not None and (type(through) is not int or through<1):
                return {"status":"error","code":"invalid_request","message":"Некорректная граница прочтения"}
            self.messages.mark_chat_read(current_user, friend, through)
            return {"status": "ok"}

        if action == "get_unread_counts":
            counts = self.messages.get_unread_counts(current_user)
            total = sum(counts.values())
            return {"status": "ok", "counts": counts, "total": total,
                    "summaries": self.messages.get_dialog_summaries(current_user)}

        # Channels
        if action == "create_channel":
            name = (data.get("name") or "").strip()
            try:
                avatar = normalize_avatar(data.get("avatar") or "")
            except ValueError as error:
                return {"status": "error", "message": str(error)}
            try:
                ch = self.channels.create_channel(current_user, name=name, avatar=avatar)
                return {"status": "ok", "channel": ch}
            except ValueError as ve:
                return {"status": "error", "message": str(ve)}
            except Exception as e:
                return {"status": "error", "message": "Не удалось создать канал"}

        if action == "join_channel":
            code = (data.get("code") or "").strip()
            ok, msg, ch = self.channels.join_channel_by_code(current_user, code)
            if ok:
                return {"status": "ok", "channel": ch}
            return {"status": "error", "message": msg}

        if action == "get_my_channels":
            channels = self.channels.list_user_channels(current_user)
            return {"status": "ok", "channels": channels}

        if action == "send_channel_invite":
            channel_id = int(data.get("channel_id") or 0)
            to_user = (data.get("to_user") or "").strip()
            ok, msg = self.channels.send_channel_invite(current_user, channel_id, to_user)
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "get_my_channel_invites":
            invites = self.channels.get_incoming_channel_invites(current_user)
            return {"status": "ok", "invites": invites}

        if action == "respond_channel_invite":
            invite_id = int(data.get("invite_id") or 0)
            decision = (data.get("decision") or "").strip().lower()
            if decision not in {"accept", "decline"}:
                return {"status": "error", "message": "Некорректное решение"}
            ok, msg, ch = self.channels.respond_channel_invite(current_user, invite_id, accept=(decision == "accept"))
            if not ok:
                return {"status": "error", "message": msg}
            return {"status": "ok", "channel": ch} if ch else {"status": "ok"}

        if action in ('get_channel_rooms','create_channel_room','rename_channel_room'):
            cid=int(data.get('channel_id') or 0)
            try:
                if action=='get_channel_rooms':
                    result = self.channels.list_rooms(current_user,cid)
                    steam_activity.enrich(self.database, [p for r in result.get('rooms',[]) for p in r.get('participants',[])])
                    return dict(status='ok', **result)
                if action=='rename_channel_room' and 'room_id' not in data:raise ValueError('Не указан канал')
                rid=self.channels.edit_room(current_user,cid,data.get('name'),data.get('kind'),data.get('room_id') if action=='rename_channel_room' else None)
                return dict(status='ok',room_id=rid)
            except ValueError as error:return dict(status='error',message=str(error))

        if action == "get_channel_messages":
            room_id=int(data.get("room_id",0))
            channel_id = int(data.get("channel_id") or 0)
            if channel_id <= 0:
                return {"status": "error", "message": "Не указан канал"}
            if not self.channels.is_channel_member(channel_id, current_user):
                return {"status": "error", "message": "Нет доступа к каналу"}
            if not self.channels.valid_room(channel_id,room_id,"text"):
                return dict(status="error",message="Текстовый канал не найден")
            if data.get('paged'):
                try:
                    return dict(status='ok', **self.channels.get_message_page(channel_id, data.get('limit',80), data.get('before_id'), data.get('after_id'), room_id=room_id))
                except ValueError as error:
                    return dict(status='error', message=str(error))
            msgs = self.channels.get_channel_messages(channel_id, limit=int(data.get("limit", 200) or 200),room_id=room_id)
            return {"status": "ok", "messages": msgs}

        if action == "send_channel_message":
            room_id=int(data.get("room_id",0))
            channel_id = int(data.get("channel_id") or 0)
            text_msg = (data.get("text") or data.get("message") or "").strip()
            if not self.channels.valid_room(channel_id,room_id,"text"):
                return dict(status="error",message="Текстовый канал не найден")
            if channel_id <= 0:
                return {"status": "error", "message": "Не указан канал"}
            if not text_msg and not data.get('attachment_id'):
                return {"status": "error", "message": "Пустое сообщение"}
            with database_connection(self.database, timeout=10) as conn:
                if not self.channels.is_channel_member(channel_id, current_user):
                    return {"status": "error", "message": "Нет доступа к каналу"}
                if not self.channels._can_send_text(conn, channel_id, current_user):
                    return {"status": "error", "message": "У вас нет прав писать в этот канал"}
            try:
                ok = self.channels.save_channel_message(channel_id, current_user, text_msg, data.get('client_message_id'),room_id=room_id, attachment_id=data.get('attachment_id'))
            except ValueError as error:
                return dict(status='error', code='request_conflict', message=str(error))
            return {"status": "ok"} if ok else {"status": "error", "message": "Не удалось отправить сообщение"}

        if action == "get_channel_details":
            channel_id = int(data.get("channel_id") or 0)
            ok, msg, details = self.channels.get_channel_details_for_user(channel_id, current_user)
            if not ok:
                return {"status": "error", "message": msg}
            return {"status": "ok", **(details or {})}

        if action == "update_channel_settings":
            channel_id = int(data.get("channel_id") or 0)
            name = (data.get("name") or "").strip()
            try:
                avatar = normalize_avatar(data.get("avatar") or "")
            except ValueError as error:
                return {"status": "error", "message": str(error)}
            text_min_role = (data.get("text_min_role") or "member").strip().lower()
            voice_min_role = (data.get("voice_min_role") or "member").strip().lower()
            ok, msg, channel = self.channels.update_channel_settings(
                current_user,
                channel_id,
                name,
                avatar,
                text_min_role=text_min_role,
                voice_min_role=voice_min_role,
            )
            if not ok:
                return {"status": "error", "message": msg}
            return {"status": "ok", "channel": channel}

        if action == "regenerate_channel_code":
            channel_id = int(data.get("channel_id") or 0)
            ok, msg, channel = self.channels.regenerate_channel_code(current_user, channel_id)
            if not ok:
                return {"status": "error", "message": msg}
            return {"status": "ok", "channel": channel}

        if action == "set_channel_member_role":
            channel_id = int(data.get("channel_id") or 0)
            target_login = (data.get("target_login") or "").strip()
            role = (data.get("role") or "").strip().lower()
            ok, msg = self.channels.set_channel_member_role(current_user, channel_id, target_login, role)
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "remove_channel_member":
            channel_id = int(data.get("channel_id") or 0)
            target_login = (data.get("target_login") or "").strip()
            ok, msg = self.channels.remove_channel_member(current_user, channel_id, target_login)
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "leave_channel":
            channel_id = int(data.get("channel_id") or 0)
            ok, msg = self.channels.leave_channel(current_user, channel_id)
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "delete_channel":
            channel_id = int(data.get("channel_id") or 0)
            ok, msg = self.channels.delete_channel(current_user, channel_id)
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "set_channel_voice_presence":
            channel_id = int(data.get("channel_id") or 0)
            speaking = bool(data.get("speaking", False))
            joined = bool(data.get("joined", True))
            ok, msg = self.channels.set_channel_voice_presence(current_user, channel_id, speaking=speaking, joined=joined, token=token, sequence=data.get("sequence"),room_id=data.get("room_id",1))
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "leave_channel_voice":
            channel_id = int(data.get("channel_id") or 0)
            ok, msg = self.channels.leave_channel_voice(current_user, channel_id, token=token, sequence=data.get("sequence"))
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "get_channel_voice_participants":
            channel_id = int(data.get("channel_id") or 0)
            ok, msg, participants = self.channels.get_channel_voice_participants(channel_id, current_user,room_id=data.get("room_id",1))
            if not ok:
                return {"status": "error", "message": msg}
            return {"status": "ok", "participants": steam_activity.enrich(self.database, participants)}

        # Calls
        if action == "call_user":
            to_user = (data.get("to_user") or "").strip()
            if not to_user:
                return {"status": "error", "message": "Не указан пользователь"}
            if to_user == current_user:
                return {"status": "error", "message": "Нельзя позвонить самому себе"}
            ok, msg = self.calls.start(current_user, to_user)
            return {"status": "ok"} if ok else {"status": "error", "message": msg}

        if action == "poll_events":
            self.calls.touch(current_user)
            if "after_event_id" in data:
                with database_connection(self.database, timeout=10) as connection:
                    connection.execute("BEGIN")
                    try:
                        events = event_store.read(connection, current_user, data["after_event_id"])
                    except ValueError as error:
                        return {"status": "error", "message": str(error)}
                    pair = connection.execute("""SELECT user_a,user_b,status,caller_login,created_at
                        FROM active_call_pairs WHERE user_a=? OR user_b=? LIMIT 1""",
                        (current_user,current_user)).fetchone()
                state = None if not pair else {
                    "peer": pair[1] if pair[0] == current_user else pair[0],
                    "status": pair[2], "incoming": pair[3] != current_user, "call_id": pair[4],
                }
                return {"status": "ok", "events": events, "call_state": state}
            events = self.events.pop_events(current_user)
            return {"status": "ok", "events": events}

        if action == "accept_call":
            from_user = (data.get("from_user") or "").strip()
            ok = self.calls.accept(current_user, from_user, expected_id=data.get("call_id"))
            return {"status": "ok"} if ok else {"status": "error", "message": "Нет активного вызова"}

        if action == "decline_call":
            from_user = (data.get("from_user") or "").strip()
            ok = self.calls.finish(current_user, from_user, decline=True, expected_id=data.get("call_id"))
            return {"status": "ok"} if ok else {"status": "error", "message": "Нет активного вызова"}

        if action == "end_call":
            with_user = (data.get("with_user") or "").strip()
            ok = self.calls.finish(current_user, with_user, expected_id=data.get("call_id"))
            return {"status": "ok"} if ok else {"status": "error", "message": "Нет активного вызова"}

        return {"status": "error", "message": "Неизвестное действие"}
