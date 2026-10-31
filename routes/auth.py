import hmac
import secrets
import time
from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
bp = Blueprint('auth', __name__)
FAILS = {}
WINDOW = 900
LIMIT = 5
def _ip():
    return request.remote_addr or 'unknown'
def _recent(ip):
    now = time.time()
    FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < WINDOW]
    if len(FAILS) > 1000:
        for k in [k for k, v in FAILS.items() if not v or now - v[-1] > WINDOW]:
            FAILS.pop(k, None)
    return FAILS[ip]
def _safe_next(target):
    if target and target.startswith('/') and (not target.startswith('//')) and ('\\' not in target):
        return target
    return url_for('dashboard.index')
@bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if session.get('auth'):
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        ip = _ip()
        recent = _recent(ip)
        if len(recent) >= LIMIT:
            wait = int(WINDOW - (time.time() - recent[0])) // 60 + 1
            error = f'Too many failed attempts. Try again in about {wait} minute(s).'
        else:
            supplied = request.form.get('password', '')
            expected = current_app.extensions['cfg'].admin_password
            if hmac.compare_digest(supplied.encode(), expected.encode()):
                FAILS.pop(ip, None)
                session.clear()
                session['auth'] = True
                session['csrf'] = secrets.token_urlsafe(32)
                session.permanent = True
                return redirect(_safe_next(request.args.get('next')))
            recent.append(time.time())
            time.sleep(0.6)
            error = 'Invalid password.'
    return (render_template('login.html', error=error), 429 if error and 'Too many' in error else 200)
@bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
