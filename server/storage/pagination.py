"""Keyset pagination scoped to one conversation; no OFFSET or history deletion."""

import sqlite3


def page(connection, table, where, params, limit=80, before_id=None, after_id=None, around_id=None, viewer=None):
    if table not in ("messages", "channel_messages"):
        raise ValueError("Unknown message table")
    allowed_where = {
        "messages": "(from_user=? AND to_user=?) OR (from_user=? AND to_user=?)",
        "channel_messages": "channel_id=? AND room_id=?",
    }
    if where != allowed_where[table]:
        raise ValueError("Unknown conversation scope")
    if sum(bool(v) for v in (before_id, after_id, around_id)) > 1:
        raise ValueError("Укажите только одно направление истории")
    connection.row_factory = sqlite3.Row
    size = min(120, max(1, int(limit)))
    boundary = ""
    values = list(params)
    cursor = before_id or after_id or around_id
    if cursor:
        anchor = connection.execute(
            f"SELECT timestamp,id FROM {table} WHERE ({where}) AND id=?",  # nosec B608: identifiers allowlisted above; values bound separately.
            (*params, cursor),
        ).fetchone()
        if anchor is None:
            raise ValueError("Сообщение истории не найдено в этом диалоге")
        boundary = " AND (timestamp,id) " + ("<" if before_id else ">") + " (?,?)"
        values.extend(anchor)
    if around_id:
        # Two bounded keyset pages, including the anchor exactly once.
        left_count = (size - 1) // 2
        right_count = size - 1 - left_count
        left = page(connection, table, where, params, max(1, left_count), before_id=around_id, viewer=viewer)
        right = page(connection, table, where, params, max(1, right_count), after_id=around_id, viewer=viewer)
        target = connection.execute(
            f'SELECT *,timestamp AS created_at FROM {table} WHERE ({where}) AND id=?',  # nosec B608: allowlisted scope.
            (*params, around_id)).fetchone()
        from .message_content import enrich
        middle = enrich(connection, [dict(target)], viewer)
        return dict(messages=(left['messages'] if left_count else []) + middle + (right['messages'] if right_count else []),
                    has_older=left['has_older'] if left_count else bool(left['messages']),
                    has_newer=right['has_newer'] if right_count else bool(right['messages']))
    direction = "ASC" if after_id else "DESC"
    raw = connection.execute(
        f"SELECT *,timestamp AS created_at FROM {table} WHERE ({where}) AND deleted_at IS NULL{boundary} ORDER BY timestamp {direction},id {direction} LIMIT ?",  # nosec B608: identifiers allowlisted above; values bound separately.
        (*values, size),
    ).fetchall()
    rows = [dict(x) for x in (raw if after_id else reversed(raw))]
    older = newer = False
    if rows:
        first, last = rows[0], rows[-1]
        older = (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE ({where}) AND deleted_at IS NULL AND (timestamp,id)<(?,?) LIMIT 1",  # nosec B608: identifiers allowlisted above; values bound separately.
                (*params, first["created_at"], first["id"]),
            ).fetchone()
            is not None
        )
        newer = (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE ({where}) AND deleted_at IS NULL AND (timestamp,id)>(?,?) LIMIT 1",  # nosec B608: identifiers allowlisted above; values bound separately.
                (*params, last["created_at"], last["id"]),
            ).fetchone()
            is not None
        )
    from .message_content import enrich
    enrich(connection, rows, viewer)
    return dict(messages=rows, has_older=older, has_newer=newer)
