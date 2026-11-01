"""Jobiew database config. No embedded usernames/passwords or local files.

Production must explicitly use WI_DB_ENGINE=postgresql and WI_DB_* values.
Development/tests can opt into WI_DB_ENGINE=sqlite. The crawler alone uses SQLite.
"""
import os
from pathlib import Path

def resolve_database(base_dir):
    mode = os.environ.get('WI_DB_ENGINE', 'postgresql').strip().lower()
    if mode in {'sqlite', 'sqlite3'}:
        if os.environ.get('DJANGO_DEBUG', '0') != '1' and os.environ.get('JOBIEW_ALLOW_TEST_SQLITE', '0') != '1':
            raise RuntimeError('SQLite is not permitted as a production Django database')
        return {'ENGINE':'django.db.backends.sqlite3', 'NAME':os.environ.get('WI_SQLITE_PATH') or str(Path(base_dir)/'db.sqlite3')}
    if mode != 'postgresql':
        raise RuntimeError('WI_DB_ENGINE must be postgresql or sqlite (development only)')
    name = os.environ.get('WI_DB_NAME')
    user = os.environ.get('WI_DB_USER')
    if not name or not user:
        raise RuntimeError('WI_DB_NAME and WI_DB_USER must be configured for PostgreSQL')
    return {
        'ENGINE':'django.db.backends.postgresql',
        'NAME':name, 'USER':user,
        'PASSWORD':os.environ.get('WI_DB_PASSWORD', ''),
        'HOST':os.environ.get('WI_DB_HOST','127.0.0.1'),
        'PORT':os.environ.get('WI_DB_PORT','5432'),
        'CONN_MAX_AGE':int(os.environ.get('WI_DB_CONN_MAX_AGE','60')),
        'OPTIONS':{'connect_timeout':8},
    }
