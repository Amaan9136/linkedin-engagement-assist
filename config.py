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
SETTING_SPECS = {'monitoring_enabled': {'type': 'bool', 'default': False, 'label': 'Check my feed for new posts', 'help': 'Turn off to pause feed checking. Work already in the queue is kept.'}, 'poll_interval': {'type': 'int', 'min': 15, 'max': 3600, 'default': 60, 'env': 'POLL_INTERVAL', 'label': 'How often to check the feed (seconds)', 'help': 'Time between feed checks. Shorter finds posts sooner but looks less natural.'}, 'lookback_days': {'type': 'int', 'min': 1, 'max': 30, 'default': 1, 'env': 'LOOKBACK_DAYS', 'label': 'First scan: how many days back to look', 'help': 'On the first run, posts up to this many days old are collected.'}, 'ai_model': {'type': 'str', 'max': 100, 'default': 'gpt-oss:20b-cloud', 'env': 'OLLAMA_MODEL', 'label': 'AI model name', 'help': 'The Ollama model that writes your comment drafts.'}, 'ollama_endpoint': {'type': 'url', 'default': 'http://localhost:11434/api/generate', 'env': 'OLLAMA_ENDPOINT', 'label': 'Ollama server address', 'help': 'Web address of your Ollama service.'}, 'ai_timeout': {'type': 'int', 'min': 5, 'max': 900, 'default': 120, 'env': 'AI_TIMEOUT', 'label': 'AI response time limit (seconds)', 'help': 'How long to wait for the AI before the attempt counts as failed.'}, 'auto_ai': {'type': 'bool', 'default': False, 'env': 'AUTO_AI', 'label': 'Write AI drafts automatically for new posts', 'help': 'When off, a draft is only written when you click Generate on the Posts page.'}, 'ai_gap': {'type': 'int', 'min': 0, 'max': 3600, 'default': 30, 'env': 'AI_GAP', 'label': 'Pause between AI requests (seconds)', 'help': 'Keeps the AI to one request at a time, with a short rest in between.'}, 'ai_hourly_limit': {'type': 'int', 'min': 0, 'max': 1000, 'default': 20, 'env': 'AI_HOURLY_LIMIT', 'label': 'Max AI drafts per hour (0 = no limit)', 'help': 'The assistant waits when this many drafts were written in the last hour.'}, 'poll_backlog_limit': {'type': 'int', 'min': 0, 'max': 1000, 'default': 10, 'env': 'POLL_BACKLOG_LIMIT', 'label': 'Wait for AI drafts before checking the feed (0 = never wait)', 'help': 'Stops checking the feed while this many AI drafts are still waiting, so posts do not pile up.'}, 'max_retries': {'type': 'int', 'min': 0, 'max': 20, 'default': 5, 'env': 'MAX_RETRIES', 'label': 'Automatic retries for a failed job', 'help': 'How many times a failed job is tried again before it is marked as failed.'}, 'backoff_base': {'type': 'int', 'min': 1, 'max': 3600, 'default': 15, 'env': 'BACKOFF_BASE', 'label': 'First retry wait (seconds)', 'help': 'How long to wait before the first retry. The wait doubles after every failure.'}, 'backoff_max': {'type': 'int', 'min': 10, 'max': 86400, 'default': 1800, 'env': 'BACKOFF_MAX', 'label': 'Longest retry wait (seconds)', 'help': 'The longest the assistant will wait between two retries.'}, 'publishing_mode': {'type': 'choice', 'choices': ['manual', 'automatic', 'mixed'], 'default': 'mixed', 'env': 'PUBLISHING_MODE', 'label': 'Publishing mode', 'help': 'Decides what the assistant does by itself and what waits for you.', 'choice_help': {'manual': 'nothing happens automatically; you like, approve and publish everything yourself', 'mixed': 'likes are automatic; comments wait for your approval', 'automatic': 'likes are automatic; comments post themselves if automatic commenting is on'}}, 'auto_like': {'type': 'bool', 'default': True, 'env': 'AUTO_LIKE', 'label': 'Like new posts automatically', 'help': 'Not used in manual mode.'}, 'auto_comment': {'type': 'bool', 'default': False, 'env': 'AUTO_COMMENT', 'label': 'Post comments automatically (automatic mode only)', 'help': 'Lets drafts post themselves. Needs the publishing mode set to automatic.'}, 'like_gap': {'type': 'int', 'min': 0, 'max': 3600, 'default': 20, 'env': 'LIKE_GAP', 'label': 'Pause between likes (seconds)', 'help': 'Minimum wait between two likes so activity looks natural.'}, 'daily_like_limit': {'type': 'int', 'min': 0, 'max': 1000, 'default': 60, 'env': 'DAILY_LIKE_LIMIT', 'label': 'Max likes per day (0 = no limit)', 'help': 'Protects your account. Liking stops once this many likes were made in the last 24 hours, then continues on its own.'}, 'like_max_age_hours': {'type': 'int', 'min': 0, 'max': 720, 'default': 72, 'env': 'LIKE_MAX_AGE_HOURS', 'label': 'Only auto-like posts newer than (hours, 0 = any age)', 'help': 'Older posts are not liked automatically.'}, 'comment_max_age_hours': {'type': 'int', 'min': 0, 'max': 720, 'default': 24, 'env': 'COMMENT_MAX_AGE_HOURS', 'label': 'Only auto-draft comments for posts newer than (hours, 0 = any age)', 'help': 'Older posts get no automatic draft. You can still generate one yourself.'}, 'comment_cooldown': {'type': 'int', 'min': 10, 'max': 86400, 'default': 60, 'env': 'COMMENT_COOLDOWN', 'label': 'Pause between comments (seconds)', 'help': 'Minimum wait between any two published comments.'}, 'daily_comment_limit': {'type': 'int', 'min': 0, 'max': 1000, 'default': 30, 'env': 'DAILY_COMMENT_LIMIT', 'label': 'Max comments per day (0 = no limit)', 'help': 'Protects your account. Commenting stops once this many comments were posted in the last 24 hours, then continues on its own.'}, 'post_retry_cooldown': {'type': 'int', 'min': 0, 'max': 86400, 'default': 150, 'env': 'POST_RETRY_COOLDOWN', 'label': 'Wait before retrying a comment on the same post (seconds)', 'help': 'Minimum wait before a failed comment on a post is tried again.'}, 'comment_style': {'type': 'str', 'max': 500, 'default': 'Casual, warm and simple. One or two short sentences. Specific to the post.', 'label': 'Comment tone and style', 'help': 'Instructions that tell the AI how your comments should sound.'}, 'max_comment_length': {'type': 'int', 'min': 20, 'max': 1250, 'default': 300, 'env': 'MAX_COMMENT_LENGTH', 'label': 'Longest comment (characters)', 'help': 'The AI will not write a comment longer than this.'}, 'batch_size': {'type': 'int', 'min': 1, 'max': 50, 'default': 5, 'env': 'BATCH_SIZE', 'label': 'Jobs handled per round', 'help': 'How many queued jobs the assistant works on in each round.'}, 'max_queue': {'type': 'int', 'min': 10, 'max': 5000, 'default': 200, 'env': 'MAX_QUEUE', 'label': 'Queue size limit', 'help': 'No new jobs are added once the queue holds this many.'}, 'log_level': {'type': 'choice', 'choices': ['DEBUG', 'INFO', 'WARNING', 'ERROR'], 'default': 'INFO', 'env': 'LOG_LEVEL', 'label': 'Log detail level', 'help': 'How much detail is written to the logs.', 'choice_help': {'DEBUG': 'everything, including technical details', 'INFO': 'normal activity, warnings and errors', 'WARNING': 'only problems that need attention', 'ERROR': 'only failures'}}, 'timezone': {'type': 'tz', 'default': 'Asia/Kolkata', 'env': 'TIMEZONE', 'label': 'Display timezone (for example Asia/Kolkata)', 'help': 'Timezone used to show times in the dashboard.'}}
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