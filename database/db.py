import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
_local = threading.local()
_path = None
recovered = None
def _heal():
    global recovered
    if not _path.exists():
        return
    try:
        c = sqlite3.connect(str(_path))
        try:
            ok = c.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        finally:
            c.close()
    except sqlite3.DatabaseError:
        ok = False
    if ok:
        return
    recovered = _path.with_name(f'{_path.name}.corrupt_{time.strftime("%Y%m%d_%H%M%S")}')
    _path.replace(recovered)
    for suffix in ('-wal', '-shm'):
        p = Path(str(_path) + suffix)
        if p.exists():
            p.replace(Path(str(recovered) + suffix))
def init(path):
    global _path
    _path = Path(path)
    _path.parent.mkdir(parents=True, exist_ok=True)
    _heal()
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
def salvage():
    global recovered
    if recovered is None:
        return
    src = sqlite3.connect(str(recovered))
    c = conn()
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_version' ORDER BY name='posts' DESC")]
    c.execute('PRAGMA foreign_keys=OFF')
    for t in names:
        cols, rows = ([], [])
        try:
            cur = src.execute(f'SELECT * FROM {t}')
            cols = [d[0] for d in cur.description]
            for r in cur:
                rows.append(tuple(r))
        except sqlite3.DatabaseError:
            pass
        if not cols:
            continue
        sql = f'INSERT OR IGNORE INTO {t}({",".join(cols)}) VALUES ({",".join("?" * len(cols))})'
        with tx():
            for r in rows:
                try:
                    c.execute(sql, r)
                except sqlite3.DatabaseError:
                    pass
    c.execute('PRAGMA foreign_keys=ON')
    src.close()
    recovered = None