import logging
from logging.handlers import RotatingFileHandler
from flask import Blueprint, current_app, request
from database import models
from services import health_service
from . import api, fail, ok
bp = Blueprint('system_api', __name__)
@bp.get('/api/health')
@api
def health():
    return ok(health=health_service.health(models.all_settings(), current_app.extensions['worker']))
@bp.post('/api/feature/<name>/<state>')
@api
def feature(name, state):
    label = {'monitoring': 'Feed checking', 'like': 'Likes', 'comment': 'Comments', 'connect': 'Connections'}.get(name)
    if not label or state not in ('pause', 'resume'):
        return fail('Unknown control', 404)
    models.set_settings({name + '_enabled': state == 'resume'})
    if state == 'resume':
        if name == 'connect':
            models.set_meta('connect_blocked_until', '')
            current_app.extensions['worker'].next_connect = 0.0
        current_app.extensions['worker'].start()
        if name == 'monitoring':
            current_app.extensions['worker'].poll_now()
    return ok(message=label + (' resumed' if state == 'resume' else ' paused. Queued work is kept.'))
@bp.post('/api/connect/retry')
@api
def retry_connect():
    models.set_settings({'connect_enabled': True})
    models.set_meta('connect_blocked_until', '')
    current_app.extensions['worker'].next_connect = 0.0
    return ok(message='Retrying connection requests now')
@bp.post('/api/comment/retry')
@api
def retry_comment():
    models.set_settings({'comment_enabled': True})
    models.set_meta('comment_block_reason', '')
    models.run_jobs_now(models.job_ids('active', 'comment'))
    current_app.extensions['worker'].start()
    return ok(message='Retrying comments now')
@bp.post('/api/browser/restart')
@api
def restart_browser():
    current_app.extensions['worker'].request_browser_restart()
    return ok(message='Browser restart requested')
@bp.get('/api/logs')
@api
def logs():
    level = request.args.get('level') or None
    component = (request.args.get('component') or '').strip()[:40] or None
    post_id = request.args.get('post_id')
    try:
        pid = int(post_id) if post_id else None
        limit = int(request.args.get('limit', 200))
    except ValueError:
        return fail('Invalid filter')
    return ok(events=models.list_events(level, component, pid, limit))
@bp.post('/api/logs/clear')
@api
def clear_logs():
    removed = models.clear_events()
    for handler in logging.getLogger().handlers:
        if isinstance(handler, RotatingFileHandler) and handler.stream:
            handler.acquire()
            try:
                handler.flush()
                handler.stream.seek(0)
                handler.stream.truncate(0)
            finally:
                handler.release()
    for old in current_app.extensions['cfg'].log_dir.glob('app.log.*'):
        old.unlink(missing_ok=True)
    logging.getLogger('linkedin.api').info('Logs cleared from the dashboard')
    return ok(message=f'Cleared {removed} log entries')