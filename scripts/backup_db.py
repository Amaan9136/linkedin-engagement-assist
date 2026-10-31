import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import load_dotenv_safe_db_path
def backup(db_path, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f'linkedin_ai_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return target
def restore(db_path, backup_file, out_dir):
    if not backup_file.exists():
        sys.exit(f'Backup not found: {backup_file}')
    check = sqlite3.connect(str(backup_file))
    try:
        if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            sys.exit('Backup failed the integrity check')
    finally:
        check.close()
    if db_path.exists():
        safety = backup(db_path, out_dir)
        print(f'Current database saved to {safety}')
    for suffix in ('-wal', '-shm'):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    shutil.copyfile(backup_file, db_path)
    print(f'Restored {backup_file} -> {db_path}')
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--restore', metavar='FILE')
    parser.add_argument('--dir', default=str(ROOT / 'backups'))
    args = parser.parse_args()
    db_path = load_dotenv_safe_db_path()
    out_dir = Path(args.dir)
    if args.restore:
        restore(db_path, Path(args.restore), out_dir)
    else:
        print(f'Backup written to {backup(db_path, out_dir)}')
if __name__ == '__main__':
    main()