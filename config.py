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
SETTING_SPECS = {'monitoring_enabled': {'type': 'bool', 'default': True, 'label': 'Monitoring enabled (polling for new posts)', 'help': 'Turns feed polling on or off; queued work is kept.'}, 'poll_interval': {'type': 'int', 'min': 15, 'max': 3600, 'default': 60, 'env': 'POLL_INTERVAL', 'label': 'Polling interval (seconds)', 'help': 'How often the feed is checked for new posts.'}, 'lookback_days': {'type': 'int', 'min': 1, 'max': 30, 'default': 7, 'env': 'LOOKBACK_DAYS', 'label': 'Initial look-back (days)', 'help': 'How far back the first scan reaches for older posts.'}, 'ai_model': {'type': 'str', 'max': 100, 'default': 'gpt-oss:20b-cloud', 'env': 'OLLAMA_MODEL', 'label': 'AI model', 'help': 'Ollama model that writes the comment drafts.'}, 'ollama_endpoint': {'type': 'url', 'default': 'http://localhost:11434/api/generate', 'env': 'OLLAMA_ENDPOINT', 'label': 'Ollama endpoint', 'help': 'Address of the Ollama generate API.'}, 'ai_timeout': {'type': 'int', 'min': 5, 'max': 900, 'default': 120, 'env': 'AI_TIMEOUT', 'label': 'AI request timeout (seconds)', 'help': 'How long to wait for Ollama before the attempt counts as failed.'}, 'auto_ai': {'type': 'bool', 'default': False, 'env': 'AUTO_AI', 'label': 'Automatic AI drafts for new posts', 'help': 'Off means no AI draft is written until you ask for one on the Posts page.'}, 'ai_gap': {'type': 'int', 'min': 0, 'max': 3600, 'default': 30, 'env': 'AI_GAP', 'label': 'Minimum seconds between AI requests', 'help': 'Keeps Ollama requests one at a time with a pause between them.'}, 'ai_hourly_limit': {'type': 'int', 'min': 0, 'max': 1000, 'default': 20, 'env': 'AI_HOURLY_LIMIT', 'label': 'Maximum AI requests per hour (0 = no limit)', 'help': 'Waits when this many drafts were written in the last hour.'}, 'max_retries': {'type': 'int', 'min': 0, 'max': 20, 'default': 5, 'env': 'MAX_RETRIES', 'label': 'Max automatic retries per job', 'help': 'How many times a failed job is retried before giving up.'}, 'backoff_base': {'type': 'int', 'min': 1, 'max': 3600, 'default': 15, 'env': 'BACKOFF_BASE', 'label': 'Retry backoff base (seconds)', 'help': 'First wait before a retry; doubles after each failure.'}, 'backoff_max': {'type': 'int', 'min': 10, 'max': 86400, 'default': 1800, 'env': 'BACKOFF_MAX', 'label': 'Retry backoff maximum (seconds)', 'help': 'Longest wait allowed between retries.'}, 'publishing_mode': {'type': 'choice', 'choices': ['manual', 'automatic', 'mixed'], 'default': 'mixed', 'env': 'PUBLISHING_MODE', 'label': 'Publishing mode', 'help': 'Decides what is posted automatically and what waits for you.', 'choice_help': {'manual': 'nothing is automatic; you like, approve and publish yourself', 'mixed': 'likes are automatic; comments wait for your approval', 'automatic': 'likes are automatic; comments post themselves if auto-commenting is on'}}, 'auto_like': {'type': 'bool', 'default': True, 'env': 'AUTO_LIKE', 'label': 'Automatic liking of new posts', 'help': 'Likes new posts by itself (not in manual mode).'}, 'auto_comment': {'type': 'bool', 'default': False, 'env': 'AUTO_COMMENT', 'label': "Automatic commenting (only in 'automatic' mode)", 'help': 'Lets drafts post themselves; needs automatic mode.'}, 'like_gap': {'type': 'int', 'min': 0, 'max': 3600, 'default': 20, 'env': 'LIKE_GAP', 'label': 'Minimum seconds between likes', 'help': 'Minimum pause between two likes to look natural.'}, 'like_max_age_hours': {'type': 'int', 'min': 0, 'max': 720, 'default': 72, 'env': 'LIKE_MAX_AGE_HOURS', 'label': "Don't auto-like posts older than (hours, 0 = no limit)", 'help': 'Skips auto-liking posts older than this; 0 means no limit.'}, 'comment_cooldown': {'type': 'int', 'min': 10, 'max': 86400, 'default': 60, 'env': 'COMMENT_COOLDOWN', 'label': 'Global comment cooldown (seconds)', 'help': 'Minimum pause between any two published comments.'}, 'post_retry_cooldown': {'type': 'int', 'min': 0, 'max': 86400, 'default': 150, 'env': 'POST_RETRY_COOLDOWN', 'label': 'Per-post retry cooldown (seconds)', 'help': 'Minimum wait before retrying a comment on the same post.'}, 'comment_style': {'type': 'str', 'max': 500, 'default': 'Casual, warm and simple. One or two short sentences. Specific to the post.', 'label': 'Comment style', 'help': 'Tone and style instructions given to the AI.'}, 'max_comment_length': {'type': 'int', 'min': 20, 'max': 1250, 'default': 300, 'env': 'MAX_COMMENT_LENGTH', 'label': 'Maximum comment length (characters)', 'help': 'Longest comment the AI may write.'}, 'batch_size': {'type': 'int', 'min': 1, 'max': 50, 'default': 5, 'env': 'BATCH_SIZE', 'label': 'Jobs processed per cycle', 'help': 'How many queued jobs run in each worker cycle.'}, 'max_queue': {'type': 'int', 'min': 10, 'max': 5000, 'default': 200, 'env': 'MAX_QUEUE', 'label': 'Maximum queued jobs', 'help': 'Stops adding new jobs when the queue reaches this size.'}, 'log_level': {'type': 'choice', 'choices': ['DEBUG', 'INFO', 'WARNING', 'ERROR'], 'default': 'INFO', 'env': 'LOG_LEVEL', 'label': 'Log level', 'help': 'How much detail is written to the logs.', 'choice_help': {'DEBUG': 'everything, including fine-grained internals', 'INFO': 'normal activity plus warnings and errors', 'WARNING': 'only problems that need attention', 'ERROR': 'only failures'}}, 'timezone': {'type': 'tz', 'default': 'Asia/Kolkata', 'env': 'TIMEZONE', 'label': 'Display timezone (IANA name, e.g. Asia/Kolkata)', 'help': 'Timezone used to display times in the dashboard.'}}
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
            raise ValueError(f'must be between {spec["min"]} and {spec["max"]}')
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
        raise ValueError(f'must be at most {spec.get("max", 500)} characters')
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
            errors.append(f'{spec.get("env", k)}: {ex}')
            out[k] = spec['default']
    if out['backoff_max'] < out['backoff_base']:
        errors.append('BACKOFF_MAX must be >= BACKOFF_BASE')
        out['backoff_max'] = max(out['backoff_max'], out['backoff_base'])
    if errors:
        raise ConfigError('Invalid configuration:\n  - ' + '\n  - '.join(errors))
    return out
def load_dotenv_safe_db_path():
    return _resolve(_env('DATABASE_PATH', 'data/linkedin_ai.db'))