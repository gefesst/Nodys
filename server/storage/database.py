"""Connection lifetime and nested units of work for service transactions."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import sqlite3

_active = ContextVar('nodys_transactions', default={})


class _TransactionConnection(sqlite3.Connection):
    def commit(self):
        # Legacy service helpers may request commit; only the outer scope commits.
        pass

    def rollback(self):
        raise RuntimeError('Nested rollback must propagate to the transaction owner')


def _key(path):
    return str(Path(path).resolve())


@contextmanager
def connect(path, **options):
    existing = _active.get().get(_key(path))
    if existing is not None:
        factory = existing.row_factory
        try:
            yield existing
        finally:
            existing.row_factory = factory
        return
    connection = sqlite3.connect(path, **options)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


@contextmanager
def unit_of_work(path):
    key = _key(path)
    if key in _active.get():
        yield _active.get()[key]
        return
    connection = sqlite3.connect(path, timeout=10, factory=_TransactionConnection)
    marker = _active.set({**_active.get(), key: connection})
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        sqlite3.Connection.commit(connection)
    except BaseException:
        sqlite3.Connection.rollback(connection)
        raise
    finally:
        _active.reset(marker)
        connection.close()
