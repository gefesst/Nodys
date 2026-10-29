"""Keyset pagination scoped to one conversation; no OFFSET or history deletion."""

import sqlite3


def page(connection, table, where, params, limit=80, before_id=None, after_id=None):
    if table not in ("messages", "channel_messages"):
        raise ValueError("Unknown message table")
    allowed_where = {
        "messages": "(from_user=? AND to_user=?) OR (from_user=? AND to_user=?)",
        "channel_messages": "channel_id=? AND room_id=?",
    }
    if where != allowed_where[table]:
        raise ValueError("Unknown conversation scope")
    if before_id and after_id:
        raise ValueError("Укажите только одно направление истории")
    connection.row_factory = sqlite3.Row
    size = min(120, max(1, int(limit)))
    boundary = ""
    values = list(params)
    cursor = before_id or after_id
    if cursor:
        anchor = connection.execute(
            f"SELECT timestamp,id FROM {table} WHERE ({where}) AND id=?",  # nosec B608: identifiers allowlisted above; values bound separately.
            (*params, cursor),
        ).fetchone()
        if anchor is None:
            raise ValueError("Сообщение истории не найдено в этом диалоге")
        boundary = " AND (timestamp,id) " + ("<" if before_id else ">") + " (?,?)"
        values.extend(anchor)
    direction = "ASC" if after_id else "DESC"
    raw = connection.execute(
        f"SELECT *,timestamp AS created_at FROM {table} WHERE ({where}){boundary} ORDER BY timestamp {direction},id {direction} LIMIT ?",  # nosec B608: identifiers allowlisted above; values bound separately.
        (*values, size),
    ).fetchall()
    rows = [dict(x) for x in (raw if after_id else reversed(raw))]
    older = newer = False
    if rows:
        first, last = rows[0], rows[-1]
        older = (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE ({where}) AND (timestamp,id)<(?,?) LIMIT 1",  # nosec B608: identifiers allowlisted above; values bound separately.
                (*params, first["created_at"], first["id"]),
            ).fetchone()
            is not None
        )
        newer = (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE ({where}) AND (timestamp,id)>(?,?) LIMIT 1",  # nosec B608: identifiers allowlisted above; values bound separately.
                (*params, last["created_at"], last["id"]),
            ).fetchone()
            is not None
        )
    from .attachments import enrich
    enrich(connection, rows)
    return dict(messages=rows, has_older=older, has_newer=newer)
