import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
class ConfigError(Exception):
    pass
def _env(name, default=''):
    v = os.environ.get(name)
    return default if v is None or v.strip() == '' else v.strip()
def _env_bool(name, default):
    return _env(name, 'true' if default else 'false').lower() in ('1', 'true', 'yes', 'on')
def _env_int(name, default, errors, lo, hi):
    raw = _env(name, str(default))
    try:
        n = int(raw)
    except ValueError:
        errors.append(f'{name} must be an integer (got {raw!r})')
        return default
    if not lo <= n <= hi:
        errors.append(f'{name} must be between {lo} and {hi} (got {n})')
        return default
    return n
def _resolve(p):
    p = Path(p).expanduser()
    return p if p.is_absolute() else BASE_DIR / p
class Config:
    def __init__(self):
        e = []
        self.flask_env = _env('FLASK_ENV', 'production')
        self.host = _env('HOST', '127.0.0.1')
        self.port = _env_int('PORT', 5000, e, 1, 65535)
        self.admin_password = _env('ADMIN_PASSWORD')
        self.secret_key = _env('SECRET_KEY')
        self.cookie_secure = _env_bool('COOKIE_SECURE', False)
        self.trust_proxy = _env_bool('TRUST_PROXY', False)
        self.session_hours = _env_int('SESSION_HOURS', 12, e, 1, 720)
        self.db_path = _resolve(_env('DATABASE_PATH', 'data/linkedin_ai.db'))
        self.log_dir = _resolve(_env('LOG_DIR', 'logs'))
        self.profile_dir = _resolve(_env('BROWSER_PROFILE_DIR', 'data/browser_profile'))
        self.headless = _env_bool('BROWSER_HEADLESS', True)
        self.chromium_exec = _env('CHROMIUM_EXECUTABLE')
        self.no_sandbox = _env_bool('BROWSER_NO_SANDBOX', False)
        self.block_media = _env_bool('BLOCK_MEDIA', True)
        self.autostart_worker = _env_bool('AUTOSTART_WORKER', True)
        self.worker_restart_delay = _env_int('WORKER_RESTART_DELAY', 10, e, 1, 3600)
        if self.admin_password in ('', 'change-me', 'changeme', 'password'):
            e.append('ADMIN_PASSWORD is not set (or is a placeholder). Set a strong password in .env')
        elif len(self.admin_password) < 10:
            e.append('ADMIN_PASSWORD must be at least 10 characters')
        if len(self.secret_key) < 32:
            e.append('SECRET_KEY must be at least 32 characters. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"')
        if self.chromium_exec and (not Path(self.chromium_exec).exists()):
            e.append(f'CHROMIUM_EXECUTABLE does not exist: {self.chromium_exec}')
        if e:
            raise ConfigError('Invalid configuration:\n  - ' + '\n  - '.join(e))
def load_config():
    return Config()
SETTING_SPECS = {'monitoring_enabled': {'type': 'bool', 'default': True, 'label': 'Monitoring enabled (polling for new posts)'}, 'poll_interval': {'type': 'int', 'min': 15, 'max': 3600, 'default': 60, 'env': 'POLL_INTERVAL', 'label': 'Polling interval (seconds)'}, 'lookback_days': {'type': 'int', 'min': 1, 'max': 30, 'default': 7, 'env': 'LOOKBACK_DAYS', 'label': 'Initial look-back (days)'}, 'ai_model': {'type': 'str', 'max': 100, 'default': 'gpt-oss:20b-cloud', 'env': 'OLLAMA_MODEL', 'label': 'AI model'}, 'ollama_endpoint': {'type': 'url', 'default': 'http://localhost:11434/api/generate', 'env': 'OLLAMA_ENDPOINT', 'label': 'Ollama endpoint'}, 'ai_timeout': {'type': 'int', 'min': 5, 'max': 900, 'default': 120, 'env': 'AI_TIMEOUT', 'label': 'AI request timeout (seconds)'}, 'max_retries': {'type': 'int', 'min': 0, 'max': 20, 'default': 5, 'env': 'MAX_RETRIES', 'label': 'Max automatic retries per job'}, 'backoff_base': {'type': 'int', 'min': 1, 'max': 3600, 'default': 30, 'env': 'BACKOFF_BASE', 'label': 'Retry backoff base (seconds)'}, 'backoff_max': {'type': 'int', 'min': 10, 'max': 86400, 'default': 1800, 'env': 'BACKOFF_MAX', 'label': 'Retry backoff maximum (seconds)'}, 'publishing_mode': {'type': 'choice', 'choices': ['manual', 'automatic', 'mixed'], 'default': 'mixed', 'env': 'PUBLISHING_MODE', 'label': 'Publishing mode'}, 'auto_like': {'type': 'bool', 'default': True, 'env': 'AUTO_LIKE', 'label': 'Automatic liking of new posts'}, 'auto_comment': {'type': 'bool', 'default': False, 'env': 'AUTO_COMMENT', 'label': "Automatic commenting (only in 'automatic' mode)"}, 'like_gap': {'type': 'int', 'min': 0, 'max': 3600, 'default': 20, 'env': 'LIKE_GAP', 'label': 'Minimum seconds between likes'}, 'like_max_age_hours': {'type': 'int', 'min': 0, 'max': 720, 'default': 72, 'env': 'LIKE_MAX_AGE_HOURS', 'label': "Don't auto-like posts older than (hours, 0 = no limit)"}, 'comment_cooldown': {'type': 'int', 'min': 10, 'max': 86400, 'default': 60, 'env': 'COMMENT_COOLDOWN', 'label': 'Global comment cooldown (seconds)'}, 'post_retry_cooldown': {'type': 'int', 'min': 0, 'max': 86400, 'default': 300, 'env': 'POST_RETRY_COOLDOWN', 'label': 'Per-post retry cooldown (seconds)'}, 'comment_style': {'type': 'str', 'max': 500, 'default': 'Natural, professional, friendly and concise. One or two sentences. Specific to the post.', 'label': 'Comment style'}, 'max_comment_length': {'type': 'int', 'min': 20, 'max': 1250, 'default': 300, 'env': 'MAX_COMMENT_LENGTH', 'label': 'Maximum comment length (characters)'}, 'batch_size': {'type': 'int', 'min': 1, 'max': 50, 'default': 5, 'env': 'BATCH_SIZE', 'label': 'Jobs processed per cycle'}, 'max_queue': {'type': 'int', 'min': 10, 'max': 5000, 'default': 200, 'env': 'MAX_QUEUE', 'label': 'Maximum queued jobs'}, 'log_level': {'type': 'choice', 'choices': ['DEBUG', 'INFO', 'WARNING', 'ERROR'], 'default': 'INFO', 'env': 'LOG_LEVEL', 'label': 'Log level'}, 'timezone': {'type': 'tz', 'default': 'UTC', 'env': 'TIMEZONE', 'label': 'Display timezone (IANA name, e.g. Asia/Kolkata)'}}
def _coerce(spec, v):
    t = spec['type']
    if t == 'bool':
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ('1', 'true', 'yes', 'on'):
            return True
        if s in ('0', 'false', 'no', 'off'):
            return False
        raise ValueError('must be true or false')
    if t == 'int':
        if isinstance(v, bool):
            raise ValueError('must be a whole number')
        try:
            n = int(str(v).strip())
        except ValueError:
            raise ValueError('must be a whole number')
        if not spec['min'] <= n <= spec['max']:
            raise ValueError(f'must be between {spec['min']} and {spec['max']}')
        return n
    s = str(v).strip()
    if t == 'choice':
        s = s.upper() if spec['choices'][0].isupper() else s.lower()
        if s not in spec['choices']:
            raise ValueError('must be one of: ' + ', '.join(spec['choices']))
        return s
    if not s:
        raise ValueError('must not be empty')
    if len(s) > spec.get('max', 500):
        raise ValueError(f'must be at most {spec.get('max', 500)} characters')
    if t == 'url':
        if not s.lower().startswith(('http://', 'https://')):
            raise ValueError('must start with http:// or https://')
    if t == 'tz':
        try:
            ZoneInfo(s)
        except Exception:
            raise ValueError('unknown timezone')
    return s
def validate_settings(data):
    clean, errors = ({}, {})
    for k, v in data.items():
        spec = SETTING_SPECS.get(k)
        if not spec:
            errors[k] = 'unknown setting'
            continue
        try:
            clean[k] = _coerce(spec, v)
        except ValueError as ex:
            errors[k] = str(ex)
    return (clean, errors)
def default_settings():
    out, errors = ({}, [])
    for k, spec in SETTING_SPECS.items():
        raw = _env(spec['env']) if 'env' in spec else ''
        val = raw if raw != '' else spec['default']
        try:
            out[k] = _coerce(spec, val)
        except ValueError as ex:
            errors.append(f'{spec.get('env', k)}: {ex}')
            out[k] = spec['default']
    if out['backoff_max'] < out['backoff_base']:
        errors.append('BACKOFF_MAX must be >= BACKOFF_BASE')
        out['backoff_max'] = max(out['backoff_max'], out['backoff_base'])
    if errors:
        raise ConfigError('Invalid configuration:\n  - ' + '\n  - '.join(errors))
    return out
def load_dotenv_safe_db_path():
    return _resolve(_env('DATABASE_PATH', 'data/linkedin_ai.db'))
