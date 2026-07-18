"""Thin MySQL connection helper. No ORM — raw SQL, explicit and auditable."""
from contextlib import contextmanager

import pymysql
import pymysql.cursors

from app.core.config import settings


def _connect():
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


@contextmanager
def get_conn():
    """Yield a connection; commit on success, rollback on error."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor():
    """Yield a cursor on a managed connection."""
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
