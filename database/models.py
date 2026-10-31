import json
import math
import time
from datetime import datetime, timedelta, timezone
from . import db
FMT = '%Y-%m-%dT%H:%M:%SZ'
def now_iso():
    return datetime.now(timezone.utc).strftime(FMT)
def iso_in(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(FMT)
def parse_iso(s):
    return datetime.strptime(s, FMT).replace(tzinfo=timezone.utc) if s else None
POST_COLS = {'external_id', 'url', 'author_name', 'author_url', 'title', 'body', 'alt_text', 'extra_text', 'published_at', 'last_checked_at', 'ai_status', 'draft', 'edited_comment', 'comment_status', 'like_status', 'skipped', 'skip_reason', 'retry_count', 'next_retry_at', 'last_error', 'verification_status', 'comment_attempts', 'comment_attempt_at', 'published_comment', 'comment_published_at', 'liked_at'}
def all_settings():
    return {r['key']: json.loads(r['value']) for r in db.query('SELECT key, value FROM settings')}
def set_settings(d):
    with db.tx() as c:
        for k, v in d.items():
            c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, json.dumps(v)))
def seed_settings(defaults):
    with db.tx() as c:
        for k, v in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k, json.dumps(v)))
def get_meta(key, default=None):
    r = db.query_one('SELECT value FROM meta WHERE key=?', (key,))
    return r['value'] if r else default
def set_meta(key, value):
    db.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
def reserve_slot(key, cooldown):
    with db.tx() as c:
        row = c.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        last = float(row['value']) if row else 0.0
        now = time.time()
        wait = last + cooldown - now
        if wait > 0:
            return max(1, math.ceil(wait))
        c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, repr(now)))
        return 0
def acquire_lease(owner, ttl=90):
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key='worker_lease'").fetchone()
        now = time.time()
        if row:
            who, exp = row['value'].split('|')
            if who != owner and float(exp) > now:
                return False
        c.execute("INSERT INTO meta(key,value) VALUES('worker_lease',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f'{owner}|{now + ttl}',))
        return True
def renew_lease(owner, ttl=90):
    return acquire_lease(owner, ttl)
def release_lease(owner):
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key='worker_lease'").fetchone()
        if row and row['value'].split('|')[0] == owner:
            c.execute("DELETE FROM meta WHERE key='worker_lease'")
def upsert_post(p):
    now = now_iso()
    with db.tx() as c:
        row = None
        if p.get('external_id'):
            row = c.execute('SELECT id, ai_status FROM posts WHERE external_id=?', (p['external_id'],)).fetchone()
        if not row:
            row = c.execute('SELECT id, ai_status FROM posts WHERE url=?', (p['url'],)).fetchone()
        if row:
            if row['ai_status'] == 'pending':
                c.execute("UPDATE posts SET last_checked_at=?,\n                    body=COALESCE(NULLIF(?,''),body), title=COALESCE(NULLIF(?,''),title),\n                    alt_text=COALESCE(NULLIF(?,''),alt_text), extra_text=COALESCE(NULLIF(?,''),extra_text),\n                    external_id=COALESCE(external_id,?) WHERE id=?", (now, p.get('body') or '', p.get('title') or '', p.get('alt_text') or '', p.get('extra_text') or '', p.get('external_id'), row['id']))
            else:
                c.execute('UPDATE posts SET last_checked_at=? WHERE id=?', (now, row['id']))
            return (row['id'], False)
        cur = c.execute('INSERT INTO posts(external_id,url,author_name,author_url,title,body,alt_text,extra_text,\n               published_at,discovered_at,last_checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (p.get('external_id'), p['url'], p.get('author_name'), p.get('author_url'), p.get('title'), p.get('body'), p.get('alt_text'), p.get('extra_text'), p.get('published_at'), now, now))
        return (cur.lastrowid, True)
def get_post(pid):
    r = db.query_one('SELECT * FROM posts WHERE id=?', (pid,))
    return dict(r) if r else None
def update_post(pid, **fields):
    bad = set(fields) - POST_COLS
    if bad:
        raise ValueError(f'Unknown post columns: {bad}')
    if not fields:
        return
    sets = ', '.join((f'{k}=?' for k in fields))
    db.execute(f'UPDATE posts SET {sets} WHERE id=?', (*fields.values(), pid))
def effective_comment(p):
    return (p.get('edited_comment') or p.get('draft') or '').strip()
def post_to_dict(p, detail=False):
    d = {'id': p['id'], 'external_id': p['external_id'], 'url': p['url'], 'author_name': p['author_name'], 'author_url': p['author_url'], 'title': p['title'], 'preview': (p['title'] or '')[:160] if not p['body'] else p['body'][:260], 'published_at': p['published_at'], 'discovered_at': p['discovered_at'], 'last_checked_at': p['last_checked_at'], 'ai_status': p['ai_status'], 'draft': p['draft'], 'edited_comment': p['edited_comment'], 'comment': effective_comment(p), 'comment_status': p['comment_status'], 'like_status': p['like_status'], 'skipped': bool(p['skipped']), 'skip_reason': p['skip_reason'], 'retry_count': p['retry_count'], 'next_retry_at': p['next_retry_at'], 'last_error': p['last_error'], 'verification_status': p['verification_status']}
    if detail:
        d.update(body=p['body'], alt_text=p['alt_text'], extra_text=p['extra_text'], published_comment=p['published_comment'], comment_published_at=p['comment_published_at'], liked_at=p['liked_at'], comment_attempts=p['comment_attempts'])
    return d
def _filter_clause(name):
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(FMT)
    table = {'all': ('1=1', ()), 'recent': ('discovered_at >= ?', (day_ago,)), 'older_unprocessed': ("discovered_at < ? AND skipped=0 AND ai_status IN ('pending','failed')", (day_ago,)), 'pending_ai': ("skipped=0 AND ai_status IN ('pending','generating')", ()), 'drafts': ("comment_status IN ('draft','approved')", ()), 'awaiting_approval': ("comment_status='draft'", ()), 'commented': ("comment_status='published'", ()), 'liked': ("like_status='liked'", ()), 'failed': ("(ai_status='failed' OR comment_status='failed' OR like_status='failed' OR EXISTS (SELECT 1 FROM jobs j WHERE j.post_id=posts.id AND (j.status='failed' OR (j.status='queued' AND j.attempts>0))))", ()), 'skipped': ('skipped=1', ()), 'verification': ("comment_status='verification_required' OR like_status='verification_required'", ())}
    return table.get(name, table['all'])
def list_posts(flt='all', q='', limit=25, offset=0):
    where, params = _filter_clause(flt)
    where = f'({where})'
    if q:
        esc = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like = f'%{esc}%'
        where += " AND (author_name LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR draft LIKE ? ESCAPE '\\')"
        params = (*params, like, like, like, like)
    total = db.query_one(f'SELECT COUNT(*) FROM posts WHERE {where}', params)[0]
    rows = db.query(f'SELECT * FROM posts WHERE {where} ORDER BY discovered_at DESC, id DESC LIMIT ? OFFSET ?', (*params, limit, offset))
    return ([dict(r) for r in rows], total)
def stats():
    def n(sql):
        return db.query_one(sql)[0]
    return {'posts_total': n('SELECT COUNT(*) FROM posts'), 'pending_ai': n("SELECT COUNT(*) FROM posts WHERE skipped=0 AND ai_status IN ('pending','generating')"), 'drafts': n("SELECT COUNT(*) FROM posts WHERE comment_status IN ('draft','approved')"), 'comments_published': n("SELECT COUNT(*) FROM posts WHERE comment_status='published'"), 'liked': n("SELECT COUNT(*) FROM posts WHERE like_status='liked'"), 'skipped': n('SELECT COUNT(*) FROM posts WHERE skipped=1'), 'failed_or_retrying': n("SELECT COUNT(*) FROM jobs WHERE status='failed' OR (status='queued' AND attempts>0)"), 'verification_required': n("SELECT COUNT(*) FROM posts WHERE comment_status='verification_required' OR like_status='verification_required'"), 'queued_jobs': n("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')")}
def queue_size():
    return db.query_one("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')")[0]
def enqueue_job(post_id, kind, delay=0, reset=True):
    now, nxt = (now_iso(), iso_in(delay))
    with db.tx() as c:
        c.execute("INSERT INTO jobs(post_id,kind,status,attempts,next_run_at,created_at,updated_at)\n               VALUES(?,?,'queued',0,?,?,?)\n               ON CONFLICT(post_id,kind) DO UPDATE SET status='queued',\n                 attempts=CASE WHEN ? THEN 0 ELSE attempts END,\n                 next_run_at=excluded.next_run_at, last_error=NULL, updated_at=excluded.updated_at\n               WHERE jobs.status!='running'", (post_id, kind, nxt, now, now, 1 if reset else 0))
def claim_due_jobs(limit, kinds):
    if not kinds:
        return []
    ph = ','.join('?' * len(kinds))
    now = now_iso()
    with db.tx() as c:
        rows = c.execute(f"SELECT * FROM jobs WHERE status='queued' AND next_run_at<=? AND kind IN ({ph}) ORDER BY next_run_at, id LIMIT ?", (now, *kinds, limit)).fetchall()
        out = [dict(r) for r in rows]
        for r in out:
            c.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (now, r['id']))
        return out
def finish_job(job_id, status='done', error=None):
    db.execute('UPDATE jobs SET status=?, last_error=?, updated_at=? WHERE id=?', (status, error, now_iso(), job_id))
def release_job(job_id):
    db.execute("UPDATE jobs SET status='queued', updated_at=? WHERE id=? AND status='running'", (now_iso(), job_id))
def reschedule_job(job_id, delay, attempts=None, error=None):
    if attempts is None:
        db.execute("UPDATE jobs SET status='queued', next_run_at=?, last_error=COALESCE(?,last_error), updated_at=? WHERE id=?", (iso_in(delay), error, now_iso(), job_id))
    else:
        db.execute("UPDATE jobs SET status='queued', next_run_at=?, attempts=?, last_error=?, updated_at=? WHERE id=?", (iso_in(delay), attempts, error, now_iso(), job_id))
def cancel_jobs(post_id):
    db.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE post_id=? AND status='queued'", (now_iso(), post_id))
def jobs_for_post(post_id):
    return [dict(r) for r in db.query('SELECT * FROM jobs WHERE post_id=? ORDER BY id', (post_id,))]
def requeue_running():
    return db.execute("UPDATE jobs SET status='queued', updated_at=? WHERE status='running'", (now_iso(),)).rowcount
def add_action(post_id, kind, status, detail=None):
    import sqlite3
    try:
        db.execute('INSERT INTO actions(post_id,kind,status,detail,created_at) VALUES(?,?,?,?,?)', (post_id, kind, status, (detail or '')[:500], now_iso()))
        return True
    except sqlite3.IntegrityError:
        return False
def has_success(post_id, kind):
    return db.query_one("SELECT 1 FROM actions WHERE post_id=? AND kind=? AND status='success'", (post_id, kind)) is not None
def actions_for_post(post_id):
    return [dict(r) for r in db.query('SELECT * FROM actions WHERE post_id=? ORDER BY id DESC', (post_id,))]
def log_event(level, component, message, post_id=None):
    try:
        db.execute('INSERT INTO events(ts,level,component,post_id,message) VALUES(?,?,?,?,?)', (now_iso(), level, component, post_id, message[:2000]))
    except Exception:
        pass
def list_events(level=None, component=None, post_id=None, limit=200):
    where, params = (['1=1'], [])
    order = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}
    if level and level in order:
        names = [k for k, v in order.items() if v >= order[level]]
        where.append(f'level IN ({','.join('?' * len(names))})')
        params += names
    if component:
        where.append('component=?')
        params.append(component)
    if post_id:
        where.append('post_id=?')
        params.append(post_id)
    rows = db.query(f'SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?', (*params, min(limit, 1000)))
    return [dict(r) for r in rows]
def prune_events(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(FMT)
    db.execute('DELETE FROM events WHERE ts < ?', (cutoff,))
