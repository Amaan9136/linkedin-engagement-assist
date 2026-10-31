import logging
import logging.handlers
class SecretFilter(logging.Filter):
    def __init__(self, secrets):
        super().__init__()
        self.secrets = [s for s in secrets if s]
    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for s in self.secrets:
            if s in msg:
                msg = msg.replace(s, '[REDACTED]')
        record.msg, record.args = (msg, ())
        return True
class DBHandler(logging.Handler):
    def emit(self, record):
        try:
            from database import models
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1]:
                msg += f' | {type(record.exc_info[1]).__name__}: {record.exc_info[1]}'
            models.log_event(record.levelname, record.name.split('.')[-1], msg, getattr(record, 'post_id', None))
        except Exception:
            pass
def setup_logging(cfg, level='INFO'):
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    flt = SecretFilter([cfg.admin_password, cfg.secret_key])
    fh = logging.handlers.RotatingFileHandler(cfg.log_dir / 'app.log', maxBytes=2000000, backupCount=5, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s'))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s'))
    dh = DBHandler()
    dh.setLevel(logging.INFO)
    for h in (fh, sh, dh):
        h.addFilter(flt)
        root.addHandler(h)
    set_level(level)
    for noisy in ('werkzeug', 'waitress', 'urllib3', 'asyncio'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
def set_level(level):
    logging.getLogger().setLevel(getattr(logging, str(level).upper(), logging.INFO))
