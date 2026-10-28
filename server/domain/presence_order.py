"""Monotonic, per-session voice updates prevent late heartbeats undoing leave."""
def accept_update(connection, token, channel_id, sequence):
    if not token:
        return sequence is None
    row = connection.execute(
        'SELECT sequence FROM voice_presence_versions WHERE token=? AND channel_id=?',
        (token, channel_id)).fetchone()
    if sequence is None:
        return row is None
    if type(sequence) is not int or not 0 <= sequence <= 9223372036854775807:
        raise ValueError('Некорректный номер голосового обновления')
    if row and sequence <= row[0]:
        return False
    connection.execute('''INSERT INTO voice_presence_versions(token,channel_id,sequence)
        VALUES(?,?,?) ON CONFLICT(token,channel_id) DO UPDATE SET sequence=excluded.sequence''',
        (token,channel_id,sequence))
    return True
