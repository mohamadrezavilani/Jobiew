"""Jobiew PostgreSQL configuration.

On a developer's workstation, explicitly selected PostgreSQL may load the
existing private data/postgres_local.json file (never in Git). Linux/production
always requires explicit WI_DB_* environment variables.
"""
import json
import os
from pathlib import Path


def _private_local_postgres(base_dir):
    if os.environ.get('DJANGO_DEBUG') != '1':
        return None
    path = Path(os.environ.get('WI_PG_CONFIG_PATH') or (Path(base_dir) / 'data' / 'postgres_local.json'))
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text(encoding='utf-8-sig'))
        name, user, password = cfg['database'], cfg['user'], cfg['password']
        host, port = cfg.get('host', '127.0.0.1'), str(cfg.get('port', '5432'))
        if not all(isinstance(x, str) and x.strip() for x in (name, user, password, host)):
            raise ValueError('empty or invalid required setting')
        if not port.isdecimal() or not (1 <= int(port) <= 65535):
            raise ValueError('invalid port')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError('Invalid private PostgreSQL config (data/postgres_local.json).') from exc
    return {'ENGINE': 'django.db.backends.postgresql', 'NAME': name, 'USER': user,
            'PASSWORD': password, 'HOST': host, 'PORT': port, 'CONN_MAX_AGE': 0,
            'OPTIONS': {'connect_timeout': 8}}


def resolve_database(base_dir):
    mode = os.environ.get('WI_DB_ENGINE', 'postgresql').strip().lower()
    if mode in {'sqlite', 'sqlite3'}:
        if os.environ.get('DJANGO_DEBUG') != '1' and os.environ.get('JOBIEW_ALLOW_TEST_SQLITE') != '1':
            raise RuntimeError('SQLite is not permitted as a production Django database')
        return {'ENGINE': 'django.db.backends.sqlite3',
                'NAME': os.environ.get('WI_SQLITE_PATH') or str(Path(base_dir) / 'db.sqlite3')}
    if mode != 'postgresql':
        raise RuntimeError('WI_DB_ENGINE must be postgresql or sqlite (development only)')

    # Keep production and Linux deploys independent of private Windows config.
    if os.environ.get('DJANGO_DEBUG') != '1' and os.environ.get('WI_PG_CONFIG_PATH'):
        raise RuntimeError('WI_PG_CONFIG_PATH is for development only; use WI_DB_* in production')

    # Explicit WI_DB_* settings take precedence over local JSON, e.g. in CI.
    name = os.environ.get('WI_DB_NAME')
    user = os.environ.get('WI_DB_USER')
    if name or user:
        if not name or not user:
            raise RuntimeError('Both WI_DB_NAME and WI_DB_USER must be configured')
        return {'ENGINE': 'django.db.backends.postgresql', 'NAME': name, 'USER': user,
                'PASSWORD': os.environ.get('WI_DB_PASSWORD', ''),
                'HOST': os.environ.get('WI_DB_HOST', '127.0.0.1'),
                'PORT': os.environ.get('WI_DB_PORT', '5432'),
                'CONN_MAX_AGE': int(os.environ.get('WI_DB_CONN_MAX_AGE', '60')),
                'OPTIONS': {'connect_timeout': 8}}

    local = _private_local_postgres(base_dir)
    if local is not None:
        return local
    raise RuntimeError('PostgreSQL not configured: set WI_DB_* or use the Jobiew local DB reconnect installer.')
