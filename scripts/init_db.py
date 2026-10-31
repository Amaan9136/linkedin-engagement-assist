import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ConfigError, default_settings, load_config
from database import db, migrations, models
def main():
    try:
        cfg = load_config()
        defaults = default_settings()
    except ConfigError as e:
        print(e)
        sys.exit(1)
    db.init(cfg.db_path)
    version = migrations.migrate()
    models.seed_settings(defaults)
    print(f'Database ready at {cfg.db_path} (schema version {version})')
if __name__ == '__main__':
    main()
