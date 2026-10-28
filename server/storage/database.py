"""Connections own both their transaction and their lifetime."""
from contextlib import contextmanager
import sqlite3


@contextmanager
def connect(path, **options):
    connection = sqlite3.connect(path, **options)
    try:
        with connection:
            yield connection
    finally:
        connection.close()
