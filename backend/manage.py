#!/usr/bin/env python3
"""Jobiew Django CLI.

Windows local development is opt-in through `.env.local` or, for loopback
`runserver` without any configuration, via safe development-only defaults.
Production (WSGI/Gunicorn/systemd) never uses these CLI conveniences.
"""
import os
import re
import sys
from pathlib import Path

LOCAL_ENV_KEYS = frozenset({
    'DJANGO_DEBUG', 'DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS',
    'DJANGO_CSRF_TRUSTED_ORIGINS', 'WI_DB_ENGINE', 'WI_DB_NAME',
    'WI_DB_USER', 'WI_DB_PASSWORD', 'WI_DB_HOST', 'WI_DB_PORT',
    'WI_SQLITE_PATH',
})


def _loopback_runserver(argv):
    """Refuse implicit DEBUG=1 when binding runserver to a non-local host."""
    if len(argv) < 2 or argv[1] != 'runserver':
        return True
    positional = [a for a in argv[2:] if not a.startswith('-')]
    if not positional:
        return True  # Django defaults to localhost:8000
    bind = positional[0].lower()
    return (bind.isdecimal() or bind in {'localhost', '127.0.0.1', '::1'}
            or bind.startswith(('localhost:', '127.0.0.1:', '[::1]:')))


def configure_local_environment(argv=None, environ=None, platform_name=None, project_root=None):
    """Local Windows CLI conveniences, never applied to Linux production.

    Existing environment variables take priority, so real PostgreSQL settings
    explicitly configured by a developer are preserved. No credentials are
    guessed and this does not connect to or migrate any database.
    """
    argv = list(sys.argv if argv is None else argv)
    env = os.environ if environ is None else environ
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != 'nt':
        return
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parent.parent
    local_file = root / '.env.local'
    if local_file.is_file():
        for raw in local_file.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip(), value.strip()
            if key not in LOCAL_ENV_KEYS:
                continue
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env.setdefault(key, value)
        return

    # Running `runserver 8000` in PyCharm works by default, but never expose
    # Django's DEBUG mode implicitly on 0.0.0.0 or an external interface.
    if len(argv) > 1 and argv[1] == 'runserver' and _loopback_runserver(argv):
        if 'DJANGO_DEBUG' not in env and 'DJANGO_SECRET_KEY' not in env:
            env['DJANGO_DEBUG'] = '1'
        if env.get('DJANGO_DEBUG') == '1' and 'WI_DB_ENGINE' not in env:
            if not (env.get('WI_DB_NAME') or env.get('WI_DB_USER')):
                env['WI_DB_ENGINE'] = 'sqlite'


def main():
    configure_local_environment()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'workplace_insights.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError('Django is missing. Install with: python -m pip install -r requirements.txt') from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
