import logging
import random
import re
import sys
from .errors import ActionUncertain, AuthRequired, BrowserUnavailable, PermanentError, TemporaryError
try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout
except ImportError:
    class PWError(Exception):
        pass
    class PWTimeout(Exception):
        pass
log = logging.getLogger('linkedin.browser')
FEED_URL = 'https://www.linkedin.com/feed/'
AUTH_MARKERS = ('/login', '/checkpoint', '/authwall', '/uas/', '/signup')
UNAVAILABLE_MARKERS = ('this post cannot be displayed', "this content isn't available", 'page not found')
SEL_NAV = "#global-nav, nav.global-nav, header.global-nav, header[role='banner'], nav[aria-label*='Primary'], [data-view-name^='navigation']"
SEL_UPDATE = "div.feed-shared-update-v2, div[data-urn^='urn:li:activity'], div[role='article']"
SEL_LIKE = ['button.react-button__trigger', "button[aria-label^='React Like']", "button[aria-label^='Like']"]
SEL_COMMENT_OPEN = ['button.comment-button', "button[aria-label^='Comment']"]
SEL_EDITOR = ['.comments-comment-box__form .ql-editor', '.comments-comment-box-comment__text-editor .ql-editor', "div.ql-editor[contenteditable='true']", "div[role='textbox'][contenteditable='true']"]
SEL_SUBMIT = ['button.comments-comment-box__submit-button--cr', 'button.comments-comment-box__submit-button', "form.comments-comment-box__form button[type='submit']"]
SEL_COMMENTS = 'article.comments-comment-entity, .comments-comment-item, .comments-comment-meta__description'
def _norm(s):
    return re.sub('\\s+', ' ', s or '').strip().lower()
class LinkedInBrowser:
    def __init__(self, cfg):
        self.cfg = cfg
        self._pw = None
        self._ctx = None
        self._page = None
    @property
    def started(self):
        return self._ctx is not None
    def start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable('Playwright is not installed. Run: pip install playwright && playwright install chromium') from e
        try:
            self.cfg.profile_dir.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            args = ['--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
            if sys.platform.startswith('linux'):
                args.append('--password-store=basic')
            if self.cfg.no_sandbox and sys.platform.startswith('linux'):
                args.append('--no-sandbox')
            kw = {'user_data_dir': str(self.cfg.profile_dir), 'headless': self.cfg.headless, 'args': args, 'viewport': {'width': 1280, 'height': 900} if self.cfg.headless else None, 'locale': 'en-US', 'ignore_default_args': ['--enable-automation']}
            if self.cfg.chromium_exec:
                kw['executable_path'] = self.cfg.chromium_exec
            self._ctx = self._pw.chromium.launch_persistent_context(**kw)
            if self.cfg.block_media and self.cfg.headless:
                self._ctx.route('**/*', self._route)
            self._ctx.set_default_timeout(20000)
            self._ctx.set_default_navigation_timeout(45000)
            self._page = None
            self._get_page()
            log.info('Browser started (headless=%s)', self.cfg.headless)
        except BrowserUnavailable:
            raise
        except Exception as e:
            self.stop()
            raise BrowserUnavailable(self._explain(e)) from e
    @staticmethod
    def _route(route):
        if route.request.resource_type in ('image', 'media', 'font') and (not any((h in route.request.url for h in ('google.com', 'gstatic.com', 'recaptcha')))):
            route.abort()
        else:
            route.continue_()
    @staticmethod
    def _explain(e):
        msg = str(e)
        low = msg.lower()
        if "executable doesn't exist" in low or 'playwright install' in low:
            return 'Chromium is not installed. Run: playwright install chromium'
        if 'shared libraries' in low or 'missing dependencies' in low:
            return "Missing system libraries for Chromium. Linux: 'playwright install-deps chromium'. Termux: see README"
        if 'processsingleton' in low or ('profile' in low and 'in use' in low):
            return 'The browser profile is locked by another Chromium process. Close it or stop the other instance'
        if 'no display' in low or 'xserver' in low or 'missing x server' in low:
            return 'No display available for a visible browser. Set BROWSER_HEADLESS=true or run scripts/login.py on a desktop'
        return 'Browser failed to start: ' + (msg.strip().splitlines()[0] if msg.strip() else type(e).__name__)
    def stop(self):
        for obj, fn in ((self._ctx, 'close'), (self._pw, 'stop')):
            if obj is not None:
                try:
                    getattr(obj, fn)()
                except Exception:
                    pass
        self._ctx = None
        self._pw = None
        self._page = None
    def restart(self):
        log.warning('Restarting browser')
        self.stop()
        self.start()
    def _get_page(self):
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        for extra in (pages[1:] if self.cfg.headless else []):
            try:
                extra.close()
            except Exception:
                pass
        self._page = pages[0] if pages else self._ctx.new_page()
        return self._page
    def is_alive(self):
        if not self.started:
            return False
        try:
            self._get_page().evaluate('1+1')
            return True
        except PWError as e:
            return not any((m in str(e).lower() for m in ('closed', 'disconnected', 'crashed')))
        except Exception:
            return False
    def pause(self, page, lo=700, hi=1600):
        page.wait_for_timeout(random.randint(lo, hi))
    def goto(self, url):
        page = self._get_page()
        try:
            page.goto(url, wait_until='domcontentloaded')
        except PWTimeout as e:
            raise TemporaryError(f'Navigation timed out: {url}') from e
        except PWError as e:
            msg = str(e)
            low = msg.lower()
            if 'closed' in low or 'disconnected' in low or 'crashed' in low:
                raise BrowserUnavailable('Browser disconnected') from e
            raise TemporaryError('Navigation failed: ' + msg.strip().splitlines()[0]) from e
        self.pause(page, 1000, 2000)
        self._raise_if_auth(page)
        return page
    def _raise_if_auth(self, page):
        url = page.url.lower()
        if '/checkpoint' in url:
            raise AuthRequired('LinkedIn is asking for verification (checkpoint). Complete it in a visible browser window')
        if any((m in url for m in AUTH_MARKERS)):
            raise AuthRequired('LinkedIn session is not logged in or has expired. Log in again (see README)')
    def goto_feed(self):
        page = self.goto(FEED_URL)
        try:
            page.wait_for_selector(SEL_NAV + ', ' + SEL_UPDATE, state='attached', timeout=10000)
        except PWTimeout:
            log.warning('Feed navigation bar not detected; layout may have changed')
        return page
    def check_session(self):
        try:
            if not self.cfg.headless:
                url = self._get_page().url.lower()
                if 'linkedin.com' in url and any((m in url for m in AUTH_MARKERS)):
                    return ('auth_required', 'Complete the sign-in or verification in the open browser window')
            self.goto_feed()
            return ('ok', 'Logged in')
        except AuthRequired as e:
            return ('auth_required', str(e))
    def scroll(self, page):
        page.mouse.wheel(0, random.randint(1800, 2600))
        page.wait_for_timeout(random.randint(1400, 2400))
    def _first_visible(self, scope, selectors):
        for s in selectors:
            try:
                loc = scope.locator(s).first
                if loc.count() and loc.is_visible():
                    return loc
            except (PWError, PWTimeout):
                continue
        return None
    def _open_post(self, url):
        page = self.goto(url)
        try:
            page.wait_for_selector(SEL_UPDATE, timeout=15000)
        except PWTimeout as e:
            try:
                body = _norm(page.inner_text('body'))[:3000]
            except Exception:
                body = ''
            if any((m in body for m in UNAVAILABLE_MARKERS)):
                raise PermanentError('Post is no longer available') from e
            raise TemporaryError('Post content did not load (layout change or slow network)') from e
        self.pause(page)
        return page
    @staticmethod
    def _pressed(btn):
        try:
            return btn.get_attribute('aria-pressed') == 'true'
        except (PWError, PWTimeout):
            return False
    def like_post(self, url):
        page = self._open_post(url)
        update = page.locator(SEL_UPDATE).first
        btn = self._first_visible(update, SEL_LIKE)
        if btn is None:
            raise TemporaryError('Like button not found (LinkedIn layout may have changed)')
        if self._pressed(btn):
            return 'already_liked'
        try:
            btn.click()
        except (PWError, PWTimeout) as e:
            raise TemporaryError('Could not click the like button: ' + str(e).splitlines()[0]) from e
        try:
            page.wait_for_timeout(1500)
            btn = self._first_visible(update, SEL_LIKE) or btn
            if self._pressed(btn):
                return 'liked'
        except (PWError, PWTimeout):
            pass
        raise ActionUncertain('Like was clicked but the new state could not be confirmed')
    def _comment_visible(self, page, text):
        snippet = _norm(text)[:50]
        loc = page.locator(SEL_COMMENTS)
        try:
            n = min(loc.count(), 40)
            for i in range(n):
                if snippet in _norm(loc.nth(i).inner_text()):
                    return True
        except (PWError, PWTimeout):
            return False
        return False
    def post_comment(self, url, text):
        page = self._open_post(url)
        update = page.locator(SEL_UPDATE).first
        try:
            editor = self._first_visible(update, SEL_EDITOR)
            if editor is None:
                opener = self._first_visible(update, SEL_COMMENT_OPEN)
                if opener is None:
                    raise TemporaryError('Comment button not found (LinkedIn layout may have changed)')
                opener.click()
                page.wait_for_timeout(1200)
                editor = self._first_visible(update, SEL_EDITOR)
                if editor is None:
                    raise TemporaryError('Comment box not found')
            editor.click()
            page.keyboard.insert_text(text)
            page.wait_for_timeout(900)
            submit = self._first_visible(update, SEL_SUBMIT)
            if submit is None:
                raise TemporaryError('Comment submit button not found')
            for _ in range(10):
                if submit.is_enabled():
                    break
                page.wait_for_timeout(300)
            else:
                raise TemporaryError('Comment submit button stayed disabled')
        except (PWError, PWTimeout) as e:
            raise TemporaryError('Could not prepare the comment: ' + str(e).splitlines()[0]) from e
        try:
            submit.click()
            page.wait_for_timeout(2500)
            if self._comment_visible(page, text):
                return True
        except Exception as e:
            raise ActionUncertain('Submit was clicked but the result is unknown: ' + str(e).splitlines()[0]) from e
        raise ActionUncertain('Comment was submitted but could not be confirmed on the page')
    def verify_comment(self, url, text):
        page = self._open_post(url)
        update = page.locator(SEL_UPDATE).first
        opener = self._first_visible(update, SEL_COMMENT_OPEN)
        if opener is not None:
            try:
                opener.click()
            except (PWError, PWTimeout):
                pass
        page.wait_for_timeout(2500)
        try:
            if page.locator(SEL_COMMENTS).count() == 0:
                return None
        except (PWError, PWTimeout):
            return None
        return self._comment_visible(page, text)