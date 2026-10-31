from flask import Blueprint, request
from database import models
from services import engagement_service as eng
from . import api, body, fail, ok
bp = Blueprint('posts_api', __name__)
@bp.get('/api/posts')
@api
def list_posts():
    flt = request.args.get('filter', 'all')
    q = request.args.get('q', '').strip()[:100]
    sort = request.args.get('sort', 'recent')
    try:
        page = max(1, int(request.args.get('page', 1)))
        per = min(100, max(5, int(request.args.get('per_page', 25))))
    except ValueError:
        return fail('Invalid pagination')
    rows, total = models.list_posts(flt, q, per, (page - 1) * per, sort)
    return ok(posts=[models.post_to_dict(r) for r in rows], total=total, page=page, per_page=per)
@bp.get('/api/posts/<int:pid>')
@api
def get_post(pid):
    post = models.get_post(pid)
    if not post:
        return fail('Post not found', 404)
    return ok(post=models.post_to_dict(post, detail=True), actions=models.actions_for_post(pid), jobs=models.jobs_for_post(pid))
@bp.post('/api/posts/<int:pid>/generate')
@api
def generate(pid):
    eng.request_generate(pid)
    return ok(message='Draft generation queued')
@bp.put('/api/posts/<int:pid>/comment')
@api
def edit_comment(pid):
    eng.save_edit(pid, body().get('text', ''), models.all_settings())
    return ok(message='Comment saved')
@bp.post('/api/posts/<int:pid>/approve')
@api
def approve(pid):
    eng.request_publish(pid, True, models.all_settings())
    return ok(message='Comment approved')
@bp.post('/api/posts/<int:pid>/publish')
@api
def publish(pid):
    eng.request_publish(pid, False, models.all_settings())
    return ok(message='Comment queued for publishing')
@bp.post('/api/posts/<int:pid>/like')
@api
def like(pid):
    eng.request_like(pid)
    return ok(message='Like queued')
@bp.post('/api/posts/<int:pid>/skip')
@api
def skip(pid):
    eng.skip(pid)
    return ok(message='Post skipped')
@bp.post('/api/posts/<int:pid>/reset')
@api
def reset(pid):
    eng.reset(pid, models.all_settings())
    return ok(message='Post reset')
@bp.post('/api/posts/<int:pid>/retry')
@api
def retry(pid):
    return ok(message='Retry queued: ' + ', '.join(eng.retry(pid)))
@bp.post('/api/posts/<int:pid>/confirm')
@api
def confirm(pid):
    return ok(message='Marked as done: ' + ', '.join(eng.confirm(pid)))
@bp.post('/api/posts/bulk')
@api
def bulk():
    data = body()
    action = data.get('action')
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 200 or (not all((isinstance(i, int) for i in ids))):
        return fail('Select between 1 and 200 posts')
    s = models.all_settings()
    handlers = {'generate': eng.request_generate, 'like': eng.request_like, 'skip': eng.skip, 'reset': lambda i: eng.reset(i, s), 'retry': eng.retry, 'delete': eng.delete}
    fn = handlers.get(action)
    if not fn:
        return fail('Unknown bulk action')
    done, errors = (0, [])
    for i in ids:
        try:
            fn(i)
            done += 1
        except Exception as e:
            errors.append(f'#{i}: {e}')
    return ok(done=done, errors=errors[:20], message=f'{done} of {len(ids)} post(s) updated')