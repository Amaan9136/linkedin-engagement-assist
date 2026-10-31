import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
_local = threading.local()
_path = None
def init(path):
    global _path
    _path = Path(path)
    _path.parent.mkdir(parents=True, exist_ok=True)
def conn():
    if _path is None:
        raise RuntimeError('database.db.init() has not been called')
    c = getattr(_local, 'conn', None)
    if c is None:
        c = sqlite3.connect(str(_path), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=30000')
        _local.conn = c
    return c
@contextmanager
def tx():
    c = conn()
    c.execute('BEGIN IMMEDIATE')
    try:
        yield c
    except BaseException:
        c.execute('ROLLBACK')
        raise
    else:
        c.execute('COMMIT')
def query(sql, params=()):
    return conn().execute(sql, params).fetchall()
def query_one(sql, params=()):
    return conn().execute(sql, params).fetchone()
def execute(sql, params=()):
    return conn().execute(sql, params)
