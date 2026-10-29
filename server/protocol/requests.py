"""Bounded flat request envelopes before DB or password work."""
ACTIONS = frozenset({'get_channel_rooms','create_channel_room','rename_channel_room','get_messages', 'decline_call', 'heartbeat', 'set_channel_voice_presence', 'send_message', 'logout', 'register', 'get_friends', 'accept_friend_request', 'get_my_channel_invites', 'set_channel_member_role', 'voice_ticket', 'join_channel', 'send_channel_message', 'leave_channel', 'mark_chat_read', 'leave_channel_voice', 'get_channel_messages', 'accept_call', 'find_user', 'release_call_state', 'presence_offline', 'get_channel_voice_participants', 'update_channel_settings', 'login', 'status', 'end_call', 'regenerate_channel_code', 'send_friend_request', 'decline_friend_request', 'get_channel_details', 'update_profile', 'poll_events', 'get_my_channels', 'respond_channel_invite', 'send_channel_invite', 'create_channel', 'delete_channel', 'get_unread_counts', 'resume_session', 'remove_friend', 'remove_channel_member', 'call_user', 'get_friend_requests'})
TEXT_LIMITS = {
    'kind':16, 'action':64, 'login':128, 'target_login':128, 'friend_login':128,
    'from_user':128, 'to_user':128, 'with_user':128, 'peer':128,
    'client_message_id':64, 'call_id':128, 'current_password':1024, 'request_id':64, 'password':1024, 'nickname':128, 'name':256, 'avatar':150000,
    'token':512, 'session_token':512, 'code':128, 'decision':32,
    'role':32, 'text_min_role':32, 'voice_min_role':32,
    'text':8000, 'message':8000,
}
INTEGER_LIMITS = {'room_id':(0,2**31-1),'through_id':(1,2**63-1), 'before_id':(1,2**63-1), 'after_id':(1,2**63-1), 'channel_id':(1,2**63-1), 'invite_id':(1,2**63-1),
                  'sequence':(0,2**63-1), 'after_event_id':(0,2**63-1), 'limit':(1,500)}


def validate(data):
    if not isinstance(data, dict) or len(data)>40:
        raise ValueError('Ожидается объект запроса')
    action=data.get('action')
    if not isinstance(action,str) or action not in ACTIONS:
        raise ValueError('Неизвестное действие')
    for key,value in data.items():
        if key == 'peer' and action == 'voice_ticket' and value is None:
            continue
        if key in TEXT_LIMITS:
            if not isinstance(value,str) or len(value)>TEXT_LIMITS[key] or '\x00' in value:
                raise ValueError(f'Некорректное поле: {key}')
        elif key in INTEGER_LIMITS:
            low,high=INTEGER_LIMITS[key]
            if type(value) is not int or not low<=value<=high:
                raise ValueError(f'Некорректное поле: {key}')
        elif key in ('speaking','joined','paged'):
            if type(value) is not bool:
                raise ValueError(f'Некорректное поле: {key}')
        elif key == 'room':
            if value is not None and (type(value) not in (int,str) or len(str(value))>64):
                raise ValueError('Некорректный канал')
        else:
            raise ValueError(f'Неизвестное поле: {key}')
    for field in ('role','text_min_role','voice_min_role'):
        if field in data and data[field] not in ('member','moderator','admin'):
            raise ValueError('Некорректная роль')
    if 'decision' in data and data['decision'] not in ('accept','decline'):
        raise ValueError('Некорректное решение')
    return data
