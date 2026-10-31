import threading
import time
from database import db, models
from . import ollama_service
class Runtime:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {'monitor_state': 'stopped', 'browser_status': 'stopped', 'auth_status': 'unknown', 'auth_message': '', 'ai_status': 'unknown', 'ai_message': '', 'last_poll_ok': None, 'autoscroll_until': None, 'next_poll_at': None, 'last_error': None, 'browser_error': None, 'worker_restarts': 0, 'started_at': models.now_iso()}
    def set(self, **kw):
        with self.lock:
            self.data.update(kw)
    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)
    def incr(self, key):
        with self.lock:
            self.data[key] = self.data.get(key, 0) + 1
    def snapshot(self):
        with self.lock:
            return dict(self.data)
runtime = Runtime()
_cache = {'t': 0.0, 'v': None}
def ai_health(settings, force=False):
    if not force and _cache['v'] and (time.time() - _cache['t'] < 15):
        return _cache['v']
    v = ollama_service.check(settings)
    _cache.update(t=time.time(), v=v)
    runtime.set(ai_status=v['status'], ai_message=v['message'])
    return v
def health(settings, worker):
    try:
        db.query_one('SELECT 1')
        db_ok, db_msg = (True, 'OK')
    except Exception as e:
        db_ok, db_msg = (False, str(e)[:200])
    ai = ai_health(settings, force=True)
    snap = runtime.snapshot()
    worker_alive = bool(worker and worker.alive())
    overall = 'ok' if db_ok and worker_alive and (snap['browser_status'] == 'running') and (snap['auth_status'] == 'ok') and (ai['status'] == 'up') else 'degraded'
    if not db_ok:
        overall = 'down'
    return {'status': overall, 'database': {'ok': db_ok, 'message': db_msg}, 'ai': ai, 'browser': {'status': snap['browser_status'], 'error': snap['browser_error']}, 'session': {'status': snap['auth_status'], 'message': snap['auth_message']}, 'worker': {'alive': worker_alive, 'state': snap['monitor_state'], 'restarts': snap['worker_restarts']}, 'last_poll_ok': snap['last_poll_ok'], 'next_poll_at': snap['next_poll_at']}