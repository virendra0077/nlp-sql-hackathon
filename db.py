import psycopg2
from psycopg2 import pool
import os
from contextlib import contextmanager


# Configuration — prefer env vars over hard-coded values
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "test1"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "Virendra@26"),   
}

# A single connection pool shared across the process (min 1, max 5 connections)
_pool: pool.SimpleConnectionPool | None = None


def _get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = pool.SimpleConnectionPool(1, 5, **DB_CONFIG)
    return _pool


@contextmanager
def _get_conn():
    """Yield a connection from the pool and return it when done."""
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
    """
    Execute *sql* and return all rows.
    Raises psycopg2 exceptions on failure — caller handles retries.
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def close_pool():
    """Call at shutdown to release all DB connections."""
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
    _pool = None