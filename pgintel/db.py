from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


@contextmanager
def connect(dsn: str, *, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=autocommit)
    try:
        yield conn
    finally:
        conn.close()
