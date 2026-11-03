import logging
import random
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import unquote
from .errors import ActionUncertain, AuthRequired, BrowserUnavailable, LimitReached, PermanentError, TemporaryError
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
GROW_URL = 'https://www.linkedin.com/mynetwork/grow/'
LIMIT_MSG = 'Commenting terminated: LinkedIn daily comment limit reached. Resume it from the dashboard when the limit resets'
AUTH_MARKERS = ('/login', '/checkpoint', '/authwall', '/uas/', '/signup')
UNAVAILABLE_MARKERS = ('this post cannot be displayed', "this content isn't available", 'page not found')
SEL_NAV = "#global-nav, nav.global-nav, header.global-nav, header[role='banner'], nav[aria-label*='Primary'], [data-view-name^='navigation'], [data-testid='primary-nav']"
SEL_UPDATE = "div.feed-shared-update-v2, div[data-urn^='urn:li:activity'], div[role='article'], [data-view-name='feed-full-update'], [componentkey^='update-card']"
SEL_ANY_LIKE = "button[aria-label*='like' i], button[aria-label^='Reaction button state']"
SEL_LIKE = ["button[aria-label^='Reaction button state']", 'button.react-button__trigger', "button[aria-label^='React Like']", "button[aria-label^='Like']", SEL_ANY_LIKE]
SEL_COMMENT_OPEN = ['button.comment-button', "button[aria-label^='Comment']"]
SEL_EDITOR = ["[data-testid*='text-editor'] [role='textbox'][contenteditable='true']", "div[role='textbox'][contenteditable='true'][aria-label*='comment' i]", '.comments-comment-box__form .ql-editor', '.comments-comment-box-comment__text-editor .ql-editor', "div.ql-editor[contenteditable='true']", "div[role='textbox'][contenteditable='true']"]
SEL_SUBMIT = ["[componentkey*='commentButtonSection'] button", "button:not([aria-label]):text-is('Comment')", 'button.comments-comment-box__submit-button--cr', 'button.comments-comment-box__submit-button', "form.comments-comment-box__form button[type='submit']"]
SEL_LINK_OPEN = "[aria-label='Send'], button[aria-label^='Open control menu for post by']"
SEL_CONNECT = "button[aria-label*='Invite'][aria-label*='connect' i]:not([data-skip]):visible, button:text-is('Connect'):not([data-skip]):visible"
CONNECT_LEFT_JS = "e => e.isConnected && (/^Invite .* connect/i.test(e.getAttribute('aria-label') || '') || (e.innerText || '').trim() === 'Connect')"
CONNECT_NAME_JS = "e => { let n = e; for (let i = 0; i < 8 && n; i++, n = n.parentElement) { const a = n.querySelector(\"a[href*='/in/']\"); if (a) return (a.innerText || '').trim().split('\\n')[0]; } return ''; }"
SEL_SEND_NOTE = "button[aria-label='Send without a note'], button:has-text('Send without a note')"
SEL_COMMENTS = 'article.comments-comment-entity, .comments-comment-item, .comments-comment-meta__description'
CLIP_JS = "(() => { const p = Clipboard.prototype, w = p.writeText; p.writeText = function (t) { window.__copied = t; return w.apply(this, arguments); }; document.addEventListener('copy', () => { const t = String(getSelection()); if (t) window.__copied = t; }, true); })()"
def _norm(s):
    return re.sub('\\s+', ' ', s or '').strip().lower()
class BrowserHost:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.port = 0
        self.gen = 0
        self.links = {}
        self.lock = threading.RLock()
    def ensure(self):
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._launch()
            return f'http://127.0.0.1:{self.port}'
    def restart(self):
        with self.lock:
            self._kill()
            self._launch()
    def stop(self):
        with self.lock:
            self._kill()
    def _kill(self):
        p, self.proc = (self.proc, None)
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(10)
            except Exception:
                p.kill()
    def _launch(self):
        try:
            self.cfg.profile_dir.mkdir(parents=True, exist_ok=True)
            exe = self.cfg.chromium_exec
            if not exe:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    exe = p.chromium.executable_path
            with socket.socket() as sk:
                sk.bind(('127.0.0.1', 0))
                port = sk.getsockname()[1]
            args = [exe, f'--user-data-dir={self.cfg.profile_dir}', f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--hide-crash-restore-bubble', '--lang=en-US', '--window-size=1280,900']
            if self.cfg.headless:
                args.append('--headless=new')
            if sys.platform.startswith('linux'):
                args.append('--password-store=basic')
                if self.cfg.no_sandbox:
                    args.append('--no-sandbox')
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            raise BrowserUnavailable(LinkedInBrowser._explain(e)) from e
        for _ in range(60):
            if self.proc.poll() is not None:
                break
            try:
                socket.create_connection(('127.0.0.1', port), timeout=1).close()
                self.port = port
                self.gen += 1
                log.info('Browser process started (headless=%s)', self.cfg.headless)
                return
            except OSError:
                time.sleep(0.5)
        self._kill()
        raise BrowserUnavailable('The browser did not start. Another Chromium may be using the profile, or Chromium is not installed (run: playwright install chromium)')
class LinkedInBrowser:
    def __init__(self, cfg, host):
        self.cfg = cfg
        self.host = host
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._card = None
        self._gen = 0
        self._links = host.links
        self._link_fail = 0
    def stale(self):
        return self._gen != self.host.gen
    @property
    def started(self):
        return self._ctx is not None
    def start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable('Playwright is not installed. Run: pip install playwright && playwright install chromium') from e
        try:
            endpoint = self.host.ensure()
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.connect_over_cdp(endpoint)
            self._ctx = self._browser.contexts[0]
            self._ctx.set_default_timeout(20000)
            self._ctx.set_default_navigation_timeout(45000)
            try:
                self._ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin='https://www.linkedin.com')
            except Exception:
                pass
            self._gen = self.host.gen
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
        if "no attribute '_playwright" in low:
            try:
                r = subprocess.run([sys.executable, '-m', 'playwright', '--version'], capture_output=True, text=True, timeout=30)
                probe = ((r.stdout + r.stderr).strip().splitlines() or ['no output'])[-1]
            except Exception as x:
                probe = str(x)
            return 'Playwright driver failed to start (driver check: ' + probe + '). Run: pip install --upgrade playwright greenlet && playwright install chromium'
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
        for obj, fn in ((self._page, 'close'), (self._browser, 'close'), (self._pw, 'stop')):
            if obj is not None:
                try:
                    getattr(obj, fn)()
                except Exception:
                    pass
        self._ctx = None
        self._browser = None
        self._pw = None
        self._page = None
    def restart(self):
        log.warning('Restarting browser')
        self.stop()
        self.start()
    def _get_page(self):
        if self._page is None or self._page.is_closed():
            self._page = self._ctx.new_page()
            if self.cfg.block_media and self.cfg.headless:
                self._page.route('**/*', self._route)
            self._page.add_init_script(CLIP_JS)
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
            page.wait_for_selector(SEL_NAV + ', ' + SEL_UPDATE + ', ' + SEL_ANY_LIKE, state='attached', timeout=15000)
        except PWTimeout:
            log.warning('Feed navigation bar not detected; layout may have changed')
        return page
    def check_session(self):
        try:
            if not self.cfg.headless:
                url = self._get_page().url.lower()
                if 'linkedin.com' in url and any((m in url for m in AUTH_MARKERS)) and (not any(('linkedin.com' in p.url.lower() and (not any((m in p.url.lower() for m in AUTH_MARKERS))) for p in self._ctx.pages))):
                    return ('auth_required', 'Complete the sign-in or verification in the open browser window')
            self.goto_feed()
            return ('ok', 'Logged in')
        except AuthRequired as e:
            return ('auth_required', str(e))
    def scroll(self, page):
        page.mouse.wheel(0, random.randint(1800, 2600))
        page.wait_for_timeout(random.randint(1400, 2400))
    def _scope(self, page):
        if self._card is not None:
            return self._card
        loc = page.locator(SEL_UPDATE).first
        return loc if loc.count() else page.locator('main').first
    def snapshot(self, page, name='feed_debug.html', why='No posts found'):
        try:
            path = self.cfg.log_dir / name
            path.write_text(page.content(), encoding='utf-8')
            log.warning('%s on %s (title: %s, cards: %d); page saved to %s', why, page.url, page.title(), page.locator("[componentkey^='update-card']").count(), path)
        except Exception as e:
            log.warning('Could not save feed snapshot: %s', e)
    def _first_visible(self, scope, selectors):
        for s in selectors:
            try:
                loc = scope.locator(s).first
                if loc.count() and loc.is_visible():
                    return loc
            except (PWError, PWTimeout):
                continue
        return None
    @staticmethod
    def _urn_of(text):
        m = re.search(r'(activity|share|ugcPost)[-:](\d{10,})', unquote(text or ''))
        return f'urn:li:{m.group(1)}:{m.group(2)}' if m else None
    def _resolve_short(self, url):
        if not url.startswith('http'):
            return None
        try:
            urn = self._urn_of(self._ctx.request.get(url, timeout=10000).url)
            if urn:
                return urn
        except (PWError, PWTimeout):
            pass
        tab = None
        try:
            tab = self._ctx.new_page()
            tab.goto(url, wait_until='domcontentloaded')
            tab.wait_for_url(re.compile(r'linkedin\.com/(posts|feed/update)'), timeout=8000)
            return self._urn_of(tab.url)
        except (PWError, PWTimeout):
            return None
        finally:
            if tab is not None:
                tab.close()
    def _copy_link(self, page, card):
        try:
            page.evaluate("window.__copied = null; document.querySelectorAll(\"[data-testid='toasts-title']\").forEach(h => { h.parentElement.style.display = 'none'; }); window.__old = new Set([...document.querySelectorAll(\"a[href*='lnkd%2Ein%2Fp%2F']\")].map(a => a.href))")
            scope = page.locator(f"[componentkey^='update-card'][componentkey*='{card}']").first
            if not scope.locator(SEL_LINK_OPEN).count():
                return None
            for opener in SEL_LINK_OPEN.split(', '):
                if not scope.locator(opener).count():
                    continue
                try:
                    scope.locator(opener).first.click(timeout=3000)
                    page.get_by_text(re.compile('copy link', re.I)).locator('visible=true').first.click(timeout=3000)
                    break
                except PWTimeout:
                    page.keyboard.press('Escape')
            else:
                raise PWTimeout('Copy link not found')
            for _ in range(15):
                if page.evaluate("!!(window.__copied || [...document.querySelectorAll(\"a[href*='lnkd%2Ein%2Fp%2F']\")].find(a => !window.__old.has(a.href)))"):
                    break
                page.wait_for_timeout(200)
            raw = page.evaluate("window.__copied || decodeURIComponent(([...document.querySelectorAll(\"a[href*='lnkd%2Ein%2Fp%2F']\")].find(a => !window.__old.has(a.href)) || {href: ''}).href) || Promise.race([navigator.clipboard.readText().catch(() => ''), new Promise(r => setTimeout(() => r(''), 1500))])") or ''
            raw = (re.search(r'https?://lnkd\.in/\S+?(?=&|$)', raw) or [raw])[0]
            urn = self._urn_of(raw) or self._resolve_short(raw)
            self._link_fail = 0 if urn else self._link_fail + 1
            if not urn:
                log.warning('Copied text had no post id (clipboard: %r)', raw[:120])
            page.keyboard.press('Escape')
            self.pause(page, 600, 1200)
            return urn
        except (PWError, PWTimeout) as e:
            self._link_fail += 1
            if self._link_fail == 1:
                self.snapshot(page, 'menu_debug.html', 'Copy link menu not found: ' + (str(e).splitlines() or [''])[0])
            page.keyboard.press('Escape')
            return None
    def resolve_links(self, page, items, limit=25):
        self._link_fail = 0
        for it in items:
            card = it.get('card')
            if not card or 'promoted' in (it.get('sub') or '').lower():
                continue
            if not it['urn'].startswith('card:'):
                self._links[card] = it['urn']
            elif card in self._links:
                it['urn'] = self._links[card]
            elif limit > 0 and self._link_fail < 3:
                limit -= 1
                urn = self._copy_link(page, card)
                if urn:
                    self._links[card] = urn
                    it['urn'] = urn
                    log.info('Resolved post link %s', urn)
        return items
    def _find_card(self, page, url, post):
        m = re.search(r'[?&]card=([\w-]+)', url)
        snip = _norm(post['body'] if post else '')[:40]
        cands = [page.locator(f"[componentkey^='update-card'][componentkey*='{m.group(1)}']")]
        if len(snip) >= 15:
            cands.append(page.locator("[componentkey^='update-card']").filter(has_text=snip))
        return next((c.first for c in cands if c.count()), None)
    def _open_post(self, url, post=None):
        self._card = None
        m = re.search('[?&]card=([\\w-]+)', url)
        if m and m.group(1) in self._links:
            url = f'https://www.linkedin.com/feed/update/{self._links[m.group(1)]}/'
            m = None
        if m:
            page = self._get_page()
            for attempt in range(2):
                if attempt or page.url.split('?')[0].rstrip('/') != FEED_URL.rstrip('/'):
                    page = self.goto_feed()
                else:
                    page.mouse.wheel(0, -100000)
                    page.wait_for_timeout(800)
                card = self._find_card(page, url, post)
                for _ in range(12):
                    if card:
                        break
                    page.mouse.wheel(0, 700)
                    page.wait_for_timeout(700)
                    card = self._find_card(page, url, post)
                if card:
                    break
            else:
                self.snapshot(page, 'post_debug.html', 'Post not found')
                raise TemporaryError('Post not found in the feed (it may have moved or been removed)')
            card.scroll_into_view_if_needed()
            urn = self._copy_link(page, m.group(1))
            if urn:
                self._links[m.group(1)] = urn
                return self._open_post(f'https://www.linkedin.com/feed/update/{urn}/', post)
            self._card = card
            self.pause(page)
            return page
        page = self.goto(url)
        try:
            page.wait_for_selector(SEL_UPDATE + ', main ' + SEL_ANY_LIKE, timeout=15000)
        except PWTimeout as e:
            try:
                body = _norm(page.inner_text('body'))[:3000]
            except Exception:
                body = ''
            if any((m in body for m in UNAVAILABLE_MARKERS)):
                raise PermanentError('Post is no longer available') from e
            raise TemporaryError('Post content did not load (layout change or slow network)') from e
        snip = _norm(post['body'] if post else '')[:40]
        if len(snip) >= 15 and snip not in _norm(self._scope(page).inner_text()):
            for k in [k for k, v in self._links.items() if v == self._urn_of(url)]:
                del self._links[k]
            raise PermanentError('Stored post link opens a different post, so nothing was posted')
        self.pause(page)
        return page
    @staticmethod
    def _pressed(btn):
        try:
            a = btn.get_attribute('aria-label') or ''
            return btn.get_attribute('aria-pressed') == 'true' or (a.startswith('Reaction button state') and 'no reaction' not in a)
        except (PWError, PWTimeout):
            return False
    def _like(self, page, update):
        btn = self._first_visible(update, SEL_LIKE)
        if btn is None:
            self.snapshot(page, 'action_debug.html', 'Like button not found')
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
    def like_post(self, url, post=None):
        page = self._open_post(url, post)
        return self._like(page, self._scope(page))
    def _guard_limit(self, page, pattern, kind, msg):
        try:
            hit = page.get_by_text(re.compile(pattern, re.I)).locator('visible=true').count() > 0
        except (PWError, PWTimeout):
            return
        if hit:
            page.keyboard.press('Escape')
            raise LimitReached(kind, msg)
    def connect_next(self):
        page = self._get_page()
        if not page.url.startswith(GROW_URL):
            page = self.goto(GROW_URL)
            try:
                page.wait_for_selector(SEL_CONNECT, timeout=10000)
            except PWTimeout:
                pass
        for _ in range(4):
            btn = page.locator(SEL_CONNECT).first
            if btn.count():
                break
            page.mouse.wheel(0, random.randint(700, 1000))
            page.wait_for_timeout(random.randint(1200, 1800))
        else:
            return None
        name = 'someone'
        try:
            el = btn.element_handle()
            name = re.sub('^Invite\\s+|\\s+to connect.*$', '', el.get_attribute('aria-label') or '').strip() or el.evaluate(CONNECT_NAME_JS) or name
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(random.randint(200, 500))
            el.click()
            page.wait_for_timeout(900)
            self._guard_limit(page, 'invitation limit', 'connect', 'Connections terminated: LinkedIn invitation limit reached. Resume them from the dashboard later')
            send = page.locator(SEL_SEND_NOTE).first
            if send.count():
                send.click()
                page.wait_for_timeout(700)
            if el.evaluate(CONNECT_LEFT_JS):
                el.evaluate("e => e.setAttribute('data-skip', '1')")
                page.keyboard.press('Escape')
                raise TemporaryError(f'Connect button for {name} did not change after the click')
        except (PWError, PWTimeout) as e:
            raise TemporaryError('Could not send the connection request: ' + str(e).splitlines()[0]) from e
        return name
    def _comment_visible(self, page, text):
        snippet = _norm(text)[:50]
        loc = page.locator(SEL_COMMENTS)
        try:
            n = min(loc.count(), 40)
            for i in range(n):
                if snippet in _norm(loc.nth(i).inner_text()):
                    return True
            return snippet in _norm(page.inner_text('body')) and not any(snippet in _norm(e.inner_text()) for e in page.locator(SEL_EDITOR[-1]).all())
        except (PWError, PWTimeout):
            return False
    def post_comment(self, url, text, post=None, on_like=None):
        page = self._open_post(url, post)
        update = self._scope(page)
        if on_like:
            try:
                on_like(self._like(page, update))
            except (TemporaryError, ActionUncertain, PWError, PWTimeout) as e:
                log.warning('Like before comment skipped: %s', e)
        try:
            editor = self._first_visible(update, SEL_EDITOR)
            if editor is None:
                opener = self._first_visible(update, SEL_COMMENT_OPEN)
                if opener is None:
                    self.snapshot(page, 'action_debug.html', 'Comment button not found')
                    raise TemporaryError('Comment button not found (LinkedIn layout may have changed)')
                opener.click()
                page.wait_for_timeout(1200)
                editor = self._first_visible(update, SEL_EDITOR)
                if editor is None:
                    self.snapshot(page, 'action_debug.html', 'Comment box not found')
                    raise TemporaryError('Comment box not found')
            editor.click()
            page.keyboard.insert_text(text)
            submit = None
            for _ in range(8):
                page.wait_for_timeout(400)
                self._guard_limit(page, 'daily comment limit', 'comment', LIMIT_MSG)
                submit = self._first_visible(update, SEL_SUBMIT) or self._first_visible(page, SEL_SUBMIT)
                if submit is not None:
                    break
            if submit is None:
                self.snapshot(page, 'action_debug.html', 'Comment submit button not found')
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
            for _ in range(5):
                page.wait_for_timeout(1500)
                self._guard_limit(page, 'daily comment limit', 'comment', LIMIT_MSG)
                if self._comment_visible(page, text):
                    return True
        except LimitReached:
            raise
        except Exception as e:
            raise ActionUncertain('Submit was clicked but the result is unknown: ' + str(e).splitlines()[0]) from e
        raise ActionUncertain('Comment was submitted but could not be confirmed on the page')
    def verify_comment(self, url, text, post=None):
        page = self._open_post(url, post)
        update = self._scope(page)
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