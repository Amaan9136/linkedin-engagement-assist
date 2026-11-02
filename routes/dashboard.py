from flask import Blueprint, current_app, render_template
from database import models
from services.health_service import runtime
from . import api, login_required, ok
bp = Blueprint('dashboard', __name__)
@bp.get('/')
@login_required
def index():
    return render_template('dashboard.html', page='dashboard')
@bp.get('/posts')
@login_required
def posts_page():
    return render_template('posts.html', page='posts')
@bp.get('/queue')
@login_required
def queue_page():
    return render_template('queue.html', page='queue')
@bp.get('/settings')
@login_required
def settings_page():
    return render_template('settings.html', page='settings')
@bp.get('/logs')
@login_required
def logs_page():
    return render_template('logs.html', page='logs')
@bp.get('/api/stats')
@api
def stats():
    s = models.all_settings()
    worker = current_app.extensions['worker']
    snap = runtime.snapshot()
    snap['worker_alive'] = worker.alive()
    return ok(stats=models.stats(), status=snap, config={'poll_interval': s['poll_interval'], 'publishing_mode': s['publishing_mode'], 'monitoring_enabled': s['monitoring_enabled'], 'auto_ai': s['auto_ai'], 'timezone': s['timezone'], 'daily_like_limit': s['daily_like_limit'], 'daily_comment_limit': s['daily_comment_limit'], 'daily_connect_limit': s['daily_connect_limit'], 'like_enabled': s['like_enabled'], 'comment_enabled': s['comment_enabled'], 'connect_enabled': s['connect_enabled']})