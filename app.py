import atexit
import logging
import secrets
import signal
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import Flask, abort, jsonify, request, session, url_for
import logging_setup
from config import ConfigError, default_settings, load_config
from database import db, migrations, models
from routes import auth, dashboard, jobs, posts, settings, system
from services.monitoring_worker import MonitoringWorker
log = logging.getLogger('linkedin.app')
def create_app():
    cfg = load_config()
    db.init(cfg.db_path)
    migrations.migrate()
    models.seed_settings(default_settings())
    current = models.all_settings()
    logging_setup.setup_logging(cfg, current.get('log_level', 'INFO'))
    app = Flask(__name__)
    app.config.update(SECRET_KEY=cfg.secret_key, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=cfg.cookie_secure, SESSION_COOKIE_NAME='li_assistant', PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg.session_hours), MAX_CONTENT_LENGTH=1024 * 1024)
    if cfg.trust_proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.extensions['cfg'] = cfg
    for module in (auth, dashboard, jobs, posts, settings, system):
        app.register_blueprint(module.bp)
    @app.before_request
    def guard():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            sent = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not sent or not secrets.compare_digest(sent, session['csrf']):
                if request.path.startswith('/api/'):
                    return (jsonify(ok=False, error='Invalid or missing CSRF token. Reload the page.'), 400)
                abort(400)
    @app.after_request
    def headers(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Referrer-Policy'] = 'same-origin'
        resp.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else 'public, max-age=31536000, immutable' if request.path.startswith('/static/') else 'private, no-cache'
        resp.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return resp
    def asset(name):
        return url_for('static', filename=name, v=int((Path(app.static_folder) / name).stat().st_mtime))
    @app.context_processor
    def inject():
        tz = 'UTC'
        try:
            tz = models.all_settings().get('timezone', 'UTC')
            ZoneInfo(tz)
        except Exception:
            tz = 'UTC'
        return {'csrf_token': session.get('csrf', ''), 'tz': tz, 'asset': asset}
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return (jsonify(ok=False, error='Not found'), 404)
        return ('Not found', 404)
    @app.errorhandler(Exception)
    def unhandled(e):
        code = getattr(e, 'code', None)
        if isinstance(code, int) and code < 500:
            if request.path.startswith('/api/'):
                return (jsonify(ok=False, error=getattr(e, 'description', 'Request error')), code)
            return (getattr(e, 'description', 'Request error'), code)
        log.exception('Unhandled error on %s', request.path)
        if request.path.startswith('/api/'):
            return (jsonify(ok=False, error='Internal server error'), 500)
        return ('Internal server error', 500)
    worker = MonitoringWorker(cfg)
    app.extensions['worker'] = worker
    if cfg.autostart_worker:
        worker.start()
    atexit.register(worker.stop)
    return app
def main():
    try:
        app = create_app()
    except ConfigError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    cfg = app.extensions['cfg']
    worker = app.extensions['worker']
    def shutdown(signum, frame):
        log.info('Shutdown signal received')
        worker.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    log.info('Dashboard on http://%s:%s', cfg.host, cfg.port)
    if cfg.flask_env == 'development':
        app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False, threaded=True)
    else:
        from waitress import serve
        serve(app, host=cfg.host, port=cfg.port, threads=6)
if __name__ == '__main__':
    main()