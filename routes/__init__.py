import logging
from functools import wraps
from flask import jsonify, redirect, request, session, url_for
from services.errors import AppError
log = logging.getLogger('linkedin.api')
def ok(**kw):
    return jsonify(ok=True, **kw)
def fail(msg, code=400, **kw):
    return (jsonify(ok=False, error=msg, **kw), code)
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('auth'):
            if request.path.startswith('/api/'):
                return fail('Authentication required', 401)
            return redirect(url_for('auth.login', next=request.path))
        return fn(*a, **kw)
    return wrapper
def api(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except AppError as e:
            return fail(str(e), 400)
        except Exception:
            log.exception('API error on %s', request.path)
            return fail('Internal server error', 500)
    return wrapper
def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
