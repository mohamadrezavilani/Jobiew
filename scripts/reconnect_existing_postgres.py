#!/usr/bin/env python3
"""Connect Jobiew local Django to the *existing* workplace_insights PG DB.

Read-only verification happens before ANY local configuration is changed.
Never runs migrate, creates a database, or touches the source project.
"""
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

DB_ENV_KEYS = {'WI_DB_ENGINE', 'WI_DB_NAME', 'WI_DB_USER', 'WI_DB_PASSWORD',
               'WI_DB_HOST', 'WI_DB_PORT', 'WI_SQLITE_PATH', 'WI_PG_CONFIG_PATH'}


def discover_sources(root, explicit=None):
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            p = p / 'data' / 'postgres_local.json'
        if not p.is_file():
            raise RuntimeError('Private PostgreSQL config not found at the supplied --source path.')
        return p
    base = root.parent
    candidates = (
        base / 'TestProject' / 'workplace_insights' / 'data' / 'postgres_local.json',
        base / 'workplace_insights' / 'data' / 'postgres_local.json',
        root / 'backend' / 'data' / 'postgres_local.json',
    )
    found = [p for p in candidates if p.is_file()]
    if not found:
        raise RuntimeError('Old database config not found. Expected TestProject/workplace_insights/data/postgres_local.json; use --source to specify its location.')
    # Standard old project wins over destination copy. No recursive filesystem scan.
    return found[0]


def parse_private_config(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        cfg = {k: value[k] for k in ('database', 'user', 'password')}
        cfg['host'] = value.get('host', '127.0.0.1')
        cfg['port'] = str(value.get('port', '5432'))
        if not all(isinstance(cfg[k], str) and cfg[k].strip() for k in ('database', 'user', 'password', 'host')):
            raise ValueError('required field is blank')
        if not cfg['port'].isdecimal() or not (1 <= int(cfg['port']) <= 65535):
            raise ValueError('invalid database port')
        return cfg
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Old PostgreSQL config has an invalid format (database, user, password, host, port).') from exc


def readonly_counts(config):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('psycopg not installed. Run: .venv\\Scripts\\python.exe -m pip install -r requirements.txt') from exc
    try:
        with psycopg.connect(dbname=config['database'], user=config['user'],
                             password=config['password'], host=config['host'],
                             port=config['port'], connect_timeout=8,
                             options='-c default_transaction_read_only=on') as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM companies_company')
                companies = cur.fetchone()[0]
                cur.execute('SELECT COUNT(*) FROM experiences_publicexperience')
                reviews = cur.fetchone()[0]
        if companies <= 0:
            raise RuntimeError('Connected database contains zero companies; refusing to switch.')
        return companies, reviews
    except Exception as exc:
        # Do not print SQL connection strings, which could contain secrets.
        raise RuntimeError('Could not verify original PostgreSQL database. Check PostgreSQL service, credentials and schema. Error type: ' + type(exc).__name__) from None


def update_env_text(old):
    lines = []
    seen = set()
    for raw in old.splitlines():
        stripped = raw.strip()
        key = stripped.split('=', 1)[0].strip() if '=' in stripped else ''
        if key in DB_ENV_KEYS or key in {'DJANGO_DEBUG'}:
            continue
        if key == 'DJANGO_SECRET_KEY':
            value = stripped.split('=', 1)[1].strip().strip("'\"")
            if not value or value.startswith('REPLACE_'):
                continue
            seen.add(key)
        lines.append(raw)
    if 'DJANGO_SECRET_KEY' not in seen:
        lines.append('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(48))
    lines += ['DJANGO_DEBUG=1', 'WI_DB_ENGINE=postgresql']
    return '\n'.join(lines).rstrip() + '\n'


def atomic_private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.jobiew_tmp_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def configure(root, source_path, cfg):
    dest_cfg = root / 'backend' / 'data' / 'postgres_local.json'
    env_file = root / '.env.local'
    existing_env = env_file.read_text(encoding='utf-8-sig') if env_file.is_file() else ''
    new_env = update_env_text(existing_env)
    raw_config = source_path.read_bytes()
    # Never change the original source file or allow writing over it.
    if dest_cfg.resolve() != source_path.resolve():
        atomic_private_write(dest_cfg, raw_config)
    if env_file.exists() and existing_env != new_env:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        back = root / ('.env.local.backup_' + stamp)
        if back.exists():
            raise RuntimeError('Backup path already exists; refusing overwrite.')
        shutil.copy2(env_file, back)
    if existing_env != new_env:
        atomic_private_write(env_file, new_env.encode('utf-8'))
    return dest_cfg, env_file


def verify_django(root):
    manage = root / 'backend' / 'manage.py'
    code = ("from django.db import connection; "
            "from companies.models import Company; "
            "from experiences.models import PublicExperience; "
            "print('DJANGO_DB_ENGINE=' + connection.vendor); "
            "print('DJANGO_DB_NAME=' + str(connection.settings_dict['NAME'])); "
            "print('DJANGO_COMPANIES=' + str(Company.objects.count())); "
            "print('DJANGO_EXPERIENCES=' + str(PublicExperience.objects.count()))")
    env = os.environ.copy()
    # Let the private .env.local be the sole local config, not a caller's stale
    # WI_DB_ENGINE=sqlite. Warn caller about inherited overrides explicitly.
    colliding = [k for k in DB_ENV_KEYS if k in env]
    if colliding:
        print('WARNING: Terminal environment contains DB overrides: ' + ', '.join(sorted(colliding)))
        print('If PyCharm has these overrides too, remove them in Run Configuration.')
    for key in DB_ENV_KEYS | {'DJANGO_DEBUG', 'DJANGO_SECRET_KEY'}:
        env.pop(key, None)
    cmd = [sys.executable, str(manage), 'shell', '-c', code]
    run = subprocess.run(cmd, cwd=str(root), env=env, text=True, capture_output=True)
    if run.returncode:
        print('Django check failed. First non-sensitive error line:')
        # Django errors can include sensitive data in freeform exceptions.
        print('Exit code: ' + str(run.returncode) + '. Run `python backend/manage.py check` to diagnose locally.')
        return False
    for line in run.stdout.splitlines():
        if line.startswith(('DJANGO_DB_ENGINE=', 'DJANGO_DB_NAME=', 'DJANGO_COMPANIES=', 'DJANGO_EXPERIENCES=')):
            print(line)
    return 'DJANGO_DB_ENGINE=postgresql' in run.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--source', type=str, default=None, help='Old project folder or private JSON path')
    ap.add_argument('--check', action='store_true', help='Check old DB only; no writes')
    ns = ap.parse_args(argv)
    root = ns.root.resolve()
    if not (root / 'backend' / 'manage.py').is_file():
        print('ERROR: Jobiew backend/manage.py missing from --root', file=sys.stderr)
        return 2
    try:
        src = discover_sources(root, ns.source)
        cfg = parse_private_config(src)
        print('Source config found in original project (credentials remain private).')
        print('PostgreSQL target: database=' + cfg['database'] + ' host=' + cfg['host'] + ' port=' + cfg['port'])
        company_count, experience_count = readonly_counts(cfg)
        print('READ_ONLY_ORIGINAL_COMPANIES=' + str(company_count))
        print('READ_ONLY_ORIGINAL_EXPERIENCES=' + str(experience_count))
        if ns.check:
            print('CHECK_OK: database was not changed; Jobiew config was not changed.')
            return 0
        configure(root, src, cfg)
        print('PRIVATE_CONFIGURATION_INSTALLED: Jobiew now points to the same PostgreSQL.')
        if not verify_django(root):
            print('Django verification needs attention; no database was modified.')
            return 3
        print('SUCCESS: original PostgreSQL is connected. No migrations performed.')
        return 0
    except RuntimeError as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
