"""
db.py — PostgreSQL connection pool shared across the Django process.
Drop this at the project root (same level as manage.py).
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "database": os.getenv("DB_NAME",     "test1"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "port":     os.getenv("DB_PORT",     "5432"),
}

_pool: pool.SimpleConnectionPool | None = None


def _get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = pool.SimpleConnectionPool(1, 5, **DB_CONFIG)
    return _pool


@contextmanager
def _get_conn():
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def run_query(sql: str) -> list[tuple]:
    """Execute SQL and return all rows."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def close_pool():
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
    _pool = None