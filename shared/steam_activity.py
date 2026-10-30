"""Presentation of explicitly client-reported Steam metadata."""
def activity_text(activity):
    if not isinstance(activity, dict) or not activity.get('nickname'):
        return ''
    nickname = activity['nickname']
    game = activity.get('game')
    return f"Играет в {game} · Steam: {nickname}" if game else f"Steam: {nickname}"
