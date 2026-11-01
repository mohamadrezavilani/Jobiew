#!/usr/bin/env python3
"""Create private, safe local Windows config; initialize *SQLite only*.

Never edits .env.local that already exists and never touches a configured
PostgreSQL database. This is for local previews, not deployment.
"""
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.env.local'
MANAGE = ROOT / 'backend' / 'manage.py'


def main():
    if os.name != 'nt':
        print('Use the Ubuntu deploy guide for Linux; this helper is Windows-only.')
        return 1
    if ENV.exists():
        print('Existing .env.local preserved. No configuration was overwritten.')
    else:
        secret = secrets.token_urlsafe(48)
        ENV.write_text(
            '# PRIVATE local development only. Never commit or deploy.\n'
            'DJANGO_DEBUG=1\n'
            f'DJANGO_SECRET_KEY={secret}\n'
            'DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,testserver\n'
            'WI_DB_ENGINE=sqlite\n', encoding='utf-8'
        )
        print('Created private .env.local. Using an empty local SQLite database.')

    # Interpret effective configuration via the actual manage.py helper.
    sys.path.insert(0, str(ROOT / 'backend'))
    from manage import configure_local_environment
    config = {}
    configure_local_environment(['manage.py','check'], config, platform_name='nt', project_root=ROOT)
    if config.get('DJANGO_DEBUG') != '1':
        print('Refusing local setup: DJANGO_DEBUG is not 1.')
        return 2
    if config.get('WI_DB_ENGINE', '').lower() != 'sqlite':
        print('PostgreSQL configured. No migrations will be run automatically.')
        print('Review the database target before running manage.py migrate manually.')
        return subprocess.call([sys.executable, str(MANAGE), 'check'], cwd=ROOT)

    print('Checking Django project...')
    status = subprocess.call([sys.executable, str(MANAGE), 'check'], cwd=ROOT)
    if status:
        return status
    print('Initializing private local SQLite schema (no production DB access)...')
    status = subprocess.call([sys.executable, str(MANAGE), 'migrate', '--noinput'], cwd=ROOT)
    if status:
        return status
    print('Local setup ready. In PyCharm run backend/manage.py runserver 8000')
    print('NOTE: Local SQLite is empty. Transfer or configure PostgreSQL to see existing company data.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
