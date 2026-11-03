import logging
from . import db
log = logging.getLogger('db.migrations')
MIGRATIONS = [(1, "\nCREATE TABLE posts (\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  external_id TEXT UNIQUE,\n  url TEXT NOT NULL UNIQUE,\n  author_name TEXT, author_url TEXT, title TEXT,\n  body TEXT, alt_text TEXT, extra_text TEXT,\n  published_at TEXT,\n  discovered_at TEXT NOT NULL,\n  last_checked_at TEXT,\n  ai_status TEXT NOT NULL DEFAULT 'pending',\n  draft TEXT, edited_comment TEXT,\n  comment_status TEXT NOT NULL DEFAULT 'none',\n  like_status TEXT NOT NULL DEFAULT 'none',\n  skipped INTEGER NOT NULL DEFAULT 0, skip_reason TEXT,\n  retry_count INTEGER NOT NULL DEFAULT 0, next_retry_at TEXT, last_error TEXT,\n  verification_status TEXT,\n  comment_attempts INTEGER NOT NULL DEFAULT 0, comment_attempt_at TEXT,\n  published_comment TEXT, comment_published_at TEXT, liked_at TEXT\n);\nCREATE INDEX idx_posts_discovered ON posts(discovered_at);\nCREATE INDEX idx_posts_published ON posts(published_at);\nCREATE INDEX idx_posts_ai ON posts(ai_status);\nCREATE INDEX idx_posts_comment ON posts(comment_status);\nCREATE INDEX idx_posts_like ON posts(like_status);\nCREATE INDEX idx_posts_skipped ON posts(skipped);\n\nCREATE TABLE jobs (\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,\n  kind TEXT NOT NULL CHECK (kind IN ('ai','like','comment')),\n  status TEXT NOT NULL DEFAULT 'queued',\n  attempts INTEGER NOT NULL DEFAULT 0,\n  next_run_at TEXT NOT NULL,\n  last_error TEXT,\n  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,\n  UNIQUE(post_id, kind)\n);\nCREATE INDEX idx_jobs_due ON jobs(status, next_run_at);\n\nCREATE TABLE actions (\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,\n  kind TEXT NOT NULL, status TEXT NOT NULL, detail TEXT,\n  created_at TEXT NOT NULL\n);\nCREATE INDEX idx_actions_post ON actions(post_id);\nCREATE UNIQUE INDEX uq_action_success ON actions(post_id, kind) WHERE status = 'success';\n\nCREATE TABLE events (\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  ts TEXT NOT NULL, level TEXT NOT NULL, component TEXT, post_id INTEGER, message TEXT NOT NULL\n);\nCREATE INDEX idx_events_ts ON events(ts);\nCREATE INDEX idx_events_level ON events(level);\nCREATE INDEX idx_events_post ON events(post_id);\n\nCREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);\nCREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);\n"), (3, "\nCREATE TABLE IF NOT EXISTS deleted_posts (key TEXT PRIMARY KEY);\n"), (4, "\nCREATE TABLE IF NOT EXISTS connections (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at TEXT NOT NULL);\nCREATE INDEX IF NOT EXISTS idx_connections_created ON connections(created_at);\nUPDATE settings SET value='120' WHERE key='daily_like_limit' AND value='60';\nUPDATE settings SET value='60' WHERE key='daily_comment_limit' AND value='30';\n"), (5, "\nALTER TABLE connections ADD COLUMN url TEXT;\n")]
def migrate():
    c = db.conn()
    c.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)')
    row = c.execute('SELECT MAX(version) FROM schema_version').fetchone()
    current = row[0] or 0
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        log.info('Applying migration %d', version)
        c.execute('BEGIN IMMEDIATE')
        try:
            for stmt in _split(sql):
                c.execute(stmt)
            c.execute('INSERT INTO schema_version(version) VALUES (?)', (version,))
            c.execute('COMMIT')
        except BaseException:
            c.execute('ROLLBACK')
            raise
    if db.recovered:
        log.warning('Database was corrupted; restoring readable rows from %s', db.recovered)
        db.salvage()
    return max([current] + [v for v, _ in MIGRATIONS])
def _split(sql):
    out = []
    for part in sql.split(';'):
        lines = [l for l in part.splitlines() if not l.strip().startswith('--')]
        stmt = '\n'.join(lines).strip()
        if stmt:
            out.append(stmt)
    return out