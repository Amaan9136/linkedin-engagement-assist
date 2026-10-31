import logging
import threading
import time
import uuid
import logging_setup
from database import models
from . import comment_service, engagement_service, health_service, ollama_service, post_collector, retry_service
from .errors import ActionUncertain, AuthRequired, BrowserUnavailable, Deferred, PermanentError, ServiceUnavailable, TemporaryError
from .linkedin_browser import FEED_URL, LinkedInBrowser
log = logging.getLogger('linkedin.worker')
runtime = health_service.runtime
class LeaseHeld(Exception):
    pass
class MonitoringWorker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stop_evt = threading.Event()
        self.thread = None
        self.owner = uuid.uuid4().hex
        self.browser = None
        self.next_poll = 0.0
        self.next_auth_check = 0.0
        self.next_ai_check = 0.0
        self.next_prune = 0.0
        self.browser_fail = 0
        self.browser_retry_at = 0.0
        self.force_restart = False
        self.ai_streak = 0
        self.ai_pause_until = 0.0
        self.browser_ok = False
        self.scroll_until = 0.0
        self.scroll_fresh = False
        self.start_lock = threading.Lock()
    def start(self):
        with self.start_lock:
            if self.alive():
                return
            self.stop_evt.clear()
            self.thread = threading.Thread(target=self._supervise, name='monitor-worker', daemon=True)
            self.thread.start()
    def stop(self, timeout=40):
        self.stop_evt.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout)
    def alive(self):
        return bool(self.thread and self.thread.is_alive())
    def request_browser_restart(self):
        self.force_restart = True
        self.browser_retry_at = 0.0
    def poll_now(self):
        self.next_poll = 0.0
    def toggle_autoscroll(self):
        if time.time() < self.scroll_until:
            self.scroll_until = 0.0
            runtime.set(autoscroll_until=None)
            return False
        self.scroll_until = time.time() + 180
        self.scroll_fresh = True
        runtime.set(autoscroll_until=models.iso_in(180))
        return True
    def _supervise(self):
        failures = 0
        while not self.stop_evt.is_set():
            started = time.time()
            try:
                self._run()
                break
            except LeaseHeld:
                runtime.set(monitor_state='stopped', last_error='Another worker process holds the lease')
                log.error('Another process is running the worker; retrying in 30s')
                self.stop_evt.wait(30)
            except Exception as e:
                if time.time() - started > 600:
                    failures = 0
                failures += 1
                runtime.set(monitor_state='recovering', last_error=f'Worker crashed: {e}'[:300])
                runtime.incr('worker_restarts')
                delay = min(300, self.cfg.worker_restart_delay * 2 ** min(failures - 1, 5))
                log.exception('Worker crashed (failure %d); restarting in %ds', failures, delay)
                self.stop_evt.wait(delay)
        runtime.set(monitor_state='stopped')
    def _run(self):
        if not models.acquire_lease(self.owner):
            raise LeaseHeld()
        try:
            retry_service.recover_interrupted()
            self.browser = LinkedInBrowser(self.cfg)
            log.info('Monitoring worker started')
            while not self.stop_evt.is_set():
                self._tick()
                self.stop_evt.wait(2)
        finally:
            self._shutdown()
    def _shutdown(self):
        try:
            if self.browser:
                self.browser.stop()
        except Exception:
            pass
        try:
            models.requeue_running()
            models.release_lease(self.owner)
        except Exception:
            pass
        runtime.set(browser_status='stopped', monitor_state='stopped')
        log.info('Monitoring worker stopped')
    def _safe(self, fn, default, *args):
        try:
            return fn(*args)
        except Exception:
            log.exception('Unexpected error in %s', getattr(fn, '__name__', 'step'))
            return default
    def _tick(self):
        s = models.all_settings()
        logging_setup.set_level(s['log_level'])
        models.renew_lease(self.owner)
        paused = not s['monitoring_enabled']
        runtime.set(monitor_state='paused' if paused else 'running')
        ready = self._safe(self._ensure_browser, False)
        self.browser_ok = bool(ready)
        self._safe(self._check_ai, None, s)
        now = time.time()
        scrolling = now < self.scroll_until
        if self.scroll_until and not scrolling:
            self.scroll_until = 0.0
            runtime.set(autoscroll_until=None)
        if scrolling and ready:
            self._safe(self._autoscroll, None, s)
        if not scrolling and not paused and now >= self.next_poll:
            if ready and (not (s['poll_backlog_limit'] and models.ai_backlog() > s['poll_backlog_limit'])):
                self.next_poll = now + s['poll_interval']
                runtime.set(next_poll_at=models.iso_in(s['poll_interval']))
                self._safe(self._poll, None, s)
            else:
                self.next_poll = now + 30
        self._safe(self._process_jobs, None, s)
        self._safe(self._maintenance, None)
    def _check_ai(self, s):
        if time.time() >= self.next_ai_check:
            self.next_ai_check = time.time() + 30
            health_service.ai_health(s, force=True)
            runtime.set(ai_usage=ollama_service.usage(s))
    def _maintenance(self):
        if time.time() >= self.next_prune:
            self.next_prune = time.time() + 3600
            models.prune_events(30)
    def _ensure_browser(self):
        now = time.time()
        if now < self.browser_retry_at:
            return runtime.get('auth_status') == 'ok' and runtime.get('browser_status') == 'running'
        b = self.browser
        try:
            if self.force_restart:
                self.force_restart = False
                b.restart()
                runtime.set(auth_status='unknown')
                self.next_auth_check = 0.0
            elif not b.started:
                b.start()
            elif not b.is_alive():
                log.warning('Browser is not responding; restarting')
                b.restart()
                runtime.set(auth_status='unknown')
                self.next_auth_check = 0.0
            runtime.set(browser_status='running', browser_error=None)
            self.browser_fail = 0
            if runtime.get('auth_status') != 'ok' and now >= self.next_auth_check:
                self.next_auth_check = now + 60
                try:
                    status, msg = b.check_session()
                except TemporaryError as e:
                    log.warning('Session check failed: %s', e)
                    self.next_auth_check = now + 30
                    return False
                prev = runtime.get('auth_status')
                runtime.set(auth_status=status, auth_message=msg)
                if status == 'ok' and prev != 'ok':
                    log.info('LinkedIn session is active')
                if status != 'ok' and prev != status:
                    log.warning('%s', msg)
            return runtime.get('auth_status') == 'ok'
        except BrowserUnavailable as e:
            self.browser_fail += 1
            delay = min(900, 30 * 2 ** min(self.browser_fail - 1, 5))
            self.browser_retry_at = now + delay
            runtime.set(browser_status='error', browser_error=str(e), auth_status='unknown')
            log.error('Browser unavailable (retry in %ds): %s', delay, e)
            return False
    def _poll(self, s):
        initial = models.get_meta('initial_done') != '1'
        try:
            posts = post_collector.collect(self.browser, deep=initial, lookback_days=s['lookback_days'])
        except AuthRequired as e:
            runtime.set(auth_status='auth_required', auth_message=str(e))
            self.next_auth_check = time.time() + 60
            log.warning('Polling paused: %s', e)
            return
        except BrowserUnavailable as e:
            log.error('Browser failure during polling: %s', e)
            self.force_restart = True
            return
        except TemporaryError as e:
            log.warning('Polling failed: %s', e)
            return
        new = self._store(posts, s)
        if initial and posts:
            models.set_meta('initial_done', '1')
        engagement_service.enqueue_orphans(s)
        runtime.set(last_poll_ok=models.now_iso(), auth_status='ok', auth_message='Logged in')
        log.info('Poll complete: %d seen, %d new', len(posts), new)
    def _store(self, posts, s):
        new = 0
        for p in posts:
            try:
                pid, created = models.upsert_post(p)
                if created:
                    new += 1
                    engagement_service.enqueue_for_new_post(pid, p, s)
            except Exception:
                log.exception('Failed to store post %s', p.get('url'))
        return new
    def _end_scroll(self, e):
        self.scroll_until = 0.0
        runtime.set(autoscroll_until=None)
        log.warning('Auto scroll stopped: %s', e)
    def _autoscroll(self, s):
        b = self.browser
        try:
            page = b._get_page()
            if self.scroll_fresh or not page.url.startswith(FEED_URL):
                self.scroll_fresh = False
                page = b.goto_feed()
            posts = post_collector.to_posts(post_collector.read_items(page, b), s['lookback_days'])
            b.scroll(page)
        except AuthRequired as e:
            runtime.set(auth_status='auth_required', auth_message=str(e))
            self.next_auth_check = time.time() + 60
            self._end_scroll(e)
            return
        except BrowserUnavailable as e:
            self.force_restart = True
            self._end_scroll(e)
            return
        except TemporaryError as e:
            self._end_scroll(e)
            return
        new = self._store(posts, s)
        if new:
            log.info('Auto scroll: %d seen, %d new', len(posts), new)
    def _process_jobs(self, s):
        kinds = []
        if time.time() >= self.ai_pause_until:
            kinds.append('ai')
        if self.browser_ok:
            kinds += ['like', 'comment']
        for job in models.claim_due_jobs(s['batch_size'], kinds):
            if self.stop_evt.is_set():
                models.release_job(job['id'])
                continue
            if job['kind'] == 'ai' and time.time() < self.ai_pause_until:
                models.release_job(job['id'])
                continue
            if job['kind'] != 'ai' and (not self.browser_ok):
                models.release_job(job['id'])
                continue
            self._run_job(job, s)
    def _run_job(self, job, s):
        post = models.get_post(job['post_id'])
        if not post:
            models.finish_job(job['id'], 'cancelled')
            return
        kind = job['kind']
        try:
            if kind == 'ai':
                comment_service.run_ai_job(job, post, s)
                self.ai_streak = 0
                runtime.set(ai_status='up', ai_message='OK')
            elif kind == 'like':
                engagement_service.run_like(job, post, self.browser, s)
            else:
                engagement_service.run_comment(job, post, self.browser, s)
            models.finish_job(job['id'], 'done')
        except Deferred as d:
            retry_service.defer(job, d.seconds, d.reason)
        except AuthRequired as e:
            self.browser_ok = False
            runtime.set(auth_status='auth_required', auth_message=str(e))
            self.next_auth_check = 0.0
            retry_service.defer(job, 60, str(e), True)
        except BrowserUnavailable as e:
            self.browser_ok = False
            self.force_restart = True
            runtime.set(browser_error=str(e))
            retry_service.defer(job, 60, str(e), True)
        except ServiceUnavailable as e:
            self.ai_streak += 1
            pause = min(s['backoff_max'], max(e.retry_after, 15 * 2 ** min(self.ai_streak - 1, 10)))
            self.ai_pause_until = time.time() + pause
            runtime.set(ai_status='down', ai_message=str(e)[:200])
            log.warning('AI service unavailable; pausing AI jobs for %ds: %s', pause, e)
            retry_service.defer(job, pause, str(e), True)
        except TemporaryError as e:
            retry_service.handle_temporary(job, e, s)
        except PermanentError as e:
            retry_service.handle_permanent(job, e)
        except ActionUncertain as e:
            models.finish_job(job['id'], 'done', str(e))
        except Exception as e:
            log.exception('Unexpected error in %s job', kind, extra={'post_id': job['post_id']})
            retry_service.handle_temporary(job, e, s)