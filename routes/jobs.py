from flask import Blueprint, current_app, request
from database import models
from . import api, body, fail, ok
bp = Blueprint('jobs_api', __name__)
def retry_job(job):
    post = models.get_post(job['post_id'])
    if not post or job['status'] not in ('failed', 'cancelled'):
        return False
    pid, kind = (post['id'], job['kind'])
    if kind == 'ai':
        models.update_post(pid, ai_status='pending', skipped=0, skip_reason=None)
    elif kind == 'like':
        models.update_post(pid, like_status='pending')
    elif models.effective_comment(post) and post['comment_status'] in ('failed', 'draft', 'approved', 'queued', 'none'):
        models.update_post(pid, comment_status='queued', last_error=None, retry_count=0, next_retry_at=None)
    else:
        return False
    models.enqueue_job(pid, kind)
    return True
@bp.get('/api/queue')
@api
def list_queue():
    status = request.args.get('status', 'active')
    kind = request.args.get('kind', 'all')
    q = request.args.get('q', '').strip()[:100]
    sort = request.args.get('sort', 'next')
    try:
        page = max(1, int(request.args.get('page', 1)))
        per = min(100, max(5, int(request.args.get('per_page', 25))))
    except ValueError:
        return fail('Invalid pagination')
    rows, total = models.list_jobs(status, kind, q, per, (page - 1) * per, sort)
    return ok(jobs=rows, total=total, page=page, per_page=per, counts=models.queue_counts(), max_queue=models.all_settings()['max_queue'])
@bp.post('/api/queue/bulk')
@api
def bulk():
    data = body()
    action = data.get('action')
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 500 or (not all((isinstance(i, int) for i in ids))):
        return fail('Select between 1 and 500 jobs')
    if action == 'cancel':
        done = models.cancel_jobs_by_ids(ids)
    elif action == 'delete':
        done = models.delete_jobs(ids)
    elif action == 'run_now':
        done = models.run_jobs_now(ids)
        current_app.extensions['worker'].poll_now()
    elif action == 'retry':
        done = sum(map(retry_job, models.jobs_by_ids(ids)))
    else:
        return fail('Unknown queue action')
    return ok(done=done, message=f'{done} of {len(ids)} job(s) updated')
@bp.post('/api/queue/clear')
@api
def clear():
    return ok(message=f'Removed {models.clear_finished()} finished job(s)')