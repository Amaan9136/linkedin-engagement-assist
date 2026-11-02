import logging
import time
from database import db, models
from .errors import ActionUncertain, Deferred, PermanentError, TemporaryError
log = logging.getLogger('linkedin.engagement')
def final_comment_text(post):
    return models.effective_comment(post)
def like_eligible(p, s):
    if s['publishing_mode'] == 'manual' or not s['auto_like']:
        return False
    if p.get('skipped'):
        return False
    return not models.too_old(p, s['like_max_age_hours'])
def enqueue_for_new_post(pid, p, s):
    if models.queue_size() >= s['max_queue']:
        log.warning('Queue full; post %s will be queued later', pid, extra={'post_id': pid})
        return
    if s['auto_ai'] and (not models.too_old(p, s['comment_max_age_hours'])):
        models.enqueue_job(pid, 'ai')
    if like_eligible(p, s):
        models.update_post(pid, like_status='pending')
        models.enqueue_job(pid, 'like')
def enqueue_orphans(s):
    ai_rows = db.query("SELECT id, published_at FROM posts WHERE skipped=0 AND ai_status='pending' AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.post_id=posts.id AND j.kind='ai') ORDER BY discovered_at DESC LIMIT 50")
    for r in (ai_rows if s['auto_ai'] else []):
        if models.queue_size() >= s['max_queue']:
            return
        if not models.too_old(dict(r), s['comment_max_age_hours']):
            models.enqueue_job(r['id'], 'ai')
    like_rows = db.query("SELECT * FROM posts WHERE skipped=0 AND like_status='none' AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.post_id=posts.id AND j.kind='like') ORDER BY discovered_at DESC LIMIT 50")
    for r in like_rows:
        if models.queue_size() >= s['max_queue']:
            return
        if like_eligible(dict(r), s):
            models.update_post(r['id'], like_status='pending')
            models.enqueue_job(r['id'], 'like')
def run_like(job, post, browser, s):
    pid = post['id']
    if post['like_status'] == 'liked' or models.has_success(pid, 'like'):
        models.update_post(pid, like_status='liked')
        return
    wait = models.daily_wait('like', s['daily_like_limit'])
    if wait > 0:
        raise Deferred(min(wait, 600), 'daily like limit reached')
    wait = models.reserve_slot('last_like_at', s['like_gap'])
    if wait > 0:
        raise Deferred(wait, 'like pacing')
    try:
        result = browser.like_post(post['url'], post)
    except ActionUncertain as e:
        models.update_post(pid, like_status='verification_required', last_error=str(e)[:500], verification_status='pending_verification')
        models.add_action(pid, 'like', 'uncertain', str(e))
        log.warning('Like outcome uncertain: %s', e, extra={'post_id': pid})
        return
    models.update_post(pid, like_status='liked', liked_at=models.now_iso(), last_error=None, retry_count=0, next_retry_at=None, verification_status='confirmed')
    models.add_action(pid, 'like', 'success', 'already liked' if result == 'already_liked' else 'liked')
    log.info('Post liked (%s)', result, extra={'post_id': pid})
def _mark_liked(pid, result):
    models.update_post(pid, like_status='liked', liked_at=models.now_iso())
    models.add_action(pid, 'like', 'success', 'already liked' if result == 'already_liked' else 'liked with comment')
    models.set_meta('last_like_at', repr(time.time()))
    log.info('Post liked with comment (%s)', result, extra={'post_id': pid})
def run_comment(job, post, browser, s):
    pid = post['id']
    if post['comment_status'] == 'published' or models.has_success(pid, 'comment'):
        return
    text = final_comment_text(post)
    if not text:
        raise PermanentError('No comment text available')
    if len(text) > 1250:
        raise PermanentError("Comment exceeds LinkedIn's 1250 character limit")
    if post['comment_status'] == 'verification_required' or post['verification_status'] == 'pending_verification':
        verdict = browser.verify_comment(post['url'], text, post)
        if verdict is True:
            _mark_published(pid, text, 'verified after uncertain submission')
            return
        if verdict is None:
            models.update_post(pid, comment_status='verification_required', last_error='Could not verify whether the comment was posted; check the post manually')
            raise TemporaryError('Verification inconclusive')
        models.update_post(pid, verification_status='confirmed_absent')
    wait = models.daily_wait('comment', s['daily_comment_limit'])
    if wait > 0:
        raise Deferred(min(wait, 600), 'daily comment limit reached')
    prev = models.get_meta('last_comment_at', '0')
    wait = models.reserve_slot('last_comment_at', s['comment_cooldown'])
    if wait > 0:
        raise Deferred(wait, 'global comment cooldown')
    models.update_post(pid, comment_status='publishing', comment_attempts=post['comment_attempts'] + 1, comment_attempt_at=models.now_iso())
    like = (lambda r: _mark_liked(pid, r)) if s['like_enabled'] and post['like_status'] not in ('liked', 'verification_required') and (not models.has_success(pid, 'like')) and models.daily_wait('like', s['daily_like_limit']) == 0 else None
    try:
        browser.post_comment(post['url'], text, post, like)
    except ActionUncertain as e:
        models.update_post(pid, comment_status='verification_required', verification_status='pending_verification', last_error=str(e)[:500])
        models.add_action(pid, 'comment', 'uncertain', str(e))
        log.warning('Comment outcome uncertain: %s', e, extra={'post_id': pid})
        return
    except BaseException:
        models.set_meta('last_comment_at', prev)
        models.update_post(pid, comment_status='queued')
        raise
    _mark_published(pid, text, 'published')
def _mark_published(pid, text, detail):
    models.update_post(pid, comment_status='published', published_comment=text, comment_published_at=models.now_iso(), last_error=None, retry_count=0, next_retry_at=None, verification_status='confirmed')
    models.add_action(pid, 'comment', 'success', detail)
    log.info('Comment %s', detail, extra={'post_id': pid})
def _need(pid):
    post = models.get_post(pid)
    if not post:
        raise PermanentError('Post not found')
    return post
def request_generate(pid):
    post = _need(pid)
    if post['comment_status'] in ('published', 'queued', 'publishing', 'verification_required'):
        raise PermanentError('Cannot regenerate while a comment is queued, published or awaiting verification')
    if db.query_one("SELECT 1 FROM jobs WHERE post_id=? AND kind='ai' AND status IN ('queued','running')", (pid,)):
        raise PermanentError('A draft for this post is already queued')
    models.update_post(pid, skipped=0, skip_reason=None, ai_status='pending', last_error=None, retry_count=0, next_retry_at=None)
    models.enqueue_job(pid, 'ai')
def request_like(pid):
    post = _need(pid)
    if post['like_status'] == 'liked':
        raise PermanentError('Post is already liked')
    models.update_post(pid, like_status='pending', last_error=None)
    models.enqueue_job(pid, 'like')
def save_edit(pid, text, s):
    post = _need(pid)
    text = ' '.join((text or '').split())
    if not text:
        raise PermanentError('Comment must not be empty')
    if len(text) > 1250:
        raise PermanentError('Comment is too long')
    if post['comment_status'] in ('published', 'publishing', 'queued', 'verification_required'):
        raise PermanentError('This comment can no longer be edited')
    models.update_post(pid, edited_comment=text, comment_status='draft')
def request_publish(pid, approve_only, s):
    post = _need(pid)
    text = final_comment_text(post)
    if not text:
        raise PermanentError('No comment to publish. Generate or write one first')
    if len(text) > 1250:
        raise PermanentError("Comment exceeds LinkedIn's 1250 character limit")
    if post['comment_status'] in ('published', 'publishing', 'verification_required'):
        raise PermanentError('Comment already published or awaiting verification. Use Retry to verify')
    if approve_only:
        if post['comment_status'] == 'queued':
            raise PermanentError('Comment is already queued')
        models.update_post(pid, comment_status='approved')
        return
    models.update_post(pid, comment_status='queued', last_error=None, retry_count=0, next_retry_at=None)
    models.enqueue_job(pid, 'comment')
def confirm(pid):
    post = _need(pid)
    done = []
    if post['comment_status'] == 'verification_required':
        _mark_published(pid, final_comment_text(post), 'confirmed manually')
        done.append('comment')
    if post['like_status'] == 'verification_required':
        models.update_post(pid, like_status='liked', liked_at=models.now_iso(), last_error=None, verification_status='confirmed')
        models.add_action(pid, 'like', 'success', 'confirmed manually')
        done.append('like')
    if not done:
        raise PermanentError('Nothing to confirm for this post')
    for k in done:
        db.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE post_id=? AND kind=? AND status='queued'", (models.now_iso(), pid, k))
    return done
def delete(pid):
    models.delete_post(_need(pid))
def skip(pid, reason='manual'):
    _need(pid)
    models.update_post(pid, skipped=1, skip_reason=reason)
    models.cancel_jobs(pid)
def reset(pid, s):
    post = _need(pid)
    fields = {'skipped': 0, 'skip_reason': None, 'last_error': None, 'retry_count': 0, 'next_retry_at': None}
    if post['ai_status'] in ('skipped_insufficient_text', 'failed'):
        fields['ai_status'] = 'pending'
    models.update_post(pid, **fields)
    if fields.get('ai_status') == 'pending' or (post['ai_status'] == 'pending' and (not post['draft'])):
        models.enqueue_job(pid, 'ai')
def retry(pid):
    post = _need(pid)
    retried = []
    for job in models.jobs_for_post(pid):
        if job['status'] not in ('failed', 'cancelled'):
            continue
        if job['kind'] == 'ai':
            models.update_post(pid, ai_status='pending', skipped=0, skip_reason=None)
        elif job['kind'] == 'like':
            models.update_post(pid, like_status='pending')
        elif job['kind'] == 'comment' and post['comment_status'] == 'failed':
            models.update_post(pid, comment_status='queued')
        models.enqueue_job(pid, job['kind'])
        retried.append(job['kind'])
    post = models.get_post(pid)
    if post['comment_status'] == 'verification_required' and 'comment' not in retried:
        models.enqueue_job(pid, 'comment')
        retried.append('comment')
    if post['like_status'] == 'verification_required' and 'like' not in retried:
        models.enqueue_job(pid, 'like')
        retried.append('like')
    if post['comment_status'] == 'failed' and 'comment' not in retried and models.effective_comment(post):
        models.update_post(pid, comment_status='queued')
        models.enqueue_job(pid, 'comment')
        retried.append('comment')
    if not retried:
        raise PermanentError('Nothing to retry for this post')
    models.update_post(pid, last_error=None, retry_count=0, next_retry_at=None)
    return retried