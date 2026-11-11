#!/usr/bin/env python3
"""Enable Jobiew's private Claude six-axis review on an existing server.

Run as root on the Jobiew host. A fresh key is read without echo and is NEVER
passed on the command line, put in Git, or printed. No API request is made.
"""

import argparse
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ENV_PATH = Path('/etc/jobiew/jobiew.env')
KEY_PATTERN = re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}\Z')
MODEL_PATTERN = re.compile(r'claude-[a-z0-9-]{4,90}\Z')
ASSIGNMENT = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=')
SETTINGS = ('ANTHROPIC_API_KEY', 'JOBIEW_CLAUDE_SIX_ENABLED',
            'JOBIEW_CLAUDE_SIX_LIMIT', 'JOBIEW_CLAUDE_SIX_MODEL')


def render_env(previous: str, settings: dict[str, str]) -> str:
    """Keep unrelated environment settings, removing conflicting duplicates."""
    result = []
    seen = set()
    for line in previous.splitlines():
        match = ASSIGNMENT.match(line)
        name = match.group(1) if match else None
        if name in settings:
            if name not in seen:
                result.append(f'{name}={settings[name]}')
                seen.add(name)
        else:
            result.append(line)
    for name in SETTINGS:
        if name not in seen and name in settings:
            result.append(f'{name}={settings[name]}')
    return '\n'.join(result).rstrip('\n') + '\n'


def read_env_flag_status(previous: str) -> dict[str, str]:
    values = {}
    for line in previous.splitlines():
        match = ASSIGNMENT.match(line)
        if match and match.group(1) in SETTINGS:
            name = match.group(1)
            values[name] = line.split('=', 1)[1].strip().strip('"\'')
    return {
        'enabled': values.get('JOBIEW_CLAUDE_SIX_ENABLED', '0'),
        'limit': values.get('JOBIEW_CLAUDE_SIX_LIMIT', '0'),
        'model': values.get('JOBIEW_CLAUDE_SIX_MODEL', 'claude-sonnet-5-5'),
        'key_present': 'yes' if values.get('ANTHROPIC_API_KEY', '') else 'no',
    }


def update_file(env_path: Path, settings: dict[str, str]) -> Path:
    """Root-only atomic replacement and root-only pre-change backup."""
    if env_path.is_symlink():
        raise ValueError('Refusing to modify a symlinked environment file')
    fd = os.open(env_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise ValueError('Environment file must be a regular root-owned file')
        with os.fdopen(fd, 'r', encoding='utf-8') as reader:
            fd = -1
            original = reader.read()
    finally:
        if fd >= 0:
            os.close(fd)

    updated = render_env(original, settings)
    if updated == original:
        return env_path

    backup_name = env_path.with_name(
        f'{env_path.name}.before_claude_v234_'
        f'{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}')
    backup_fd = os.open(backup_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(backup_fd, 'w', encoding='utf-8') as backup:
            backup.write(original)
            backup.flush()
            os.fsync(backup.fileno())
    except Exception:
        backup_name.unlink(missing_ok=True)
        raise

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', prefix=f'.{env_path.name}.',
            suffix='.tmp', dir=env_path.parent, delete=False
        ) as target:
            temp_path = Path(target.name)
            os.fchown(target.fileno(), info.st_uid, info.st_gid)
            os.fchmod(target.fileno(), 0o640)
            target.write(updated)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp_path, env_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return backup_name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Configure Claude 6+6 for the Jobiew server')
    parser.add_argument('--limit', type=int, default=20,
                        help='Total lifetime comparison requests (1..100; default: 20)')
    parser.add_argument('--model', default='claude-sonnet-5-5')
    parser.add_argument('--status', action='store_true', help='Show configuration without any secrets')
    args = parser.parse_args(argv)

    if not (1 <= args.limit <= 100):
        parser.error('--limit must be between 1 and 100')
    if not MODEL_PATTERN.fullmatch(args.model):
        parser.error('Invalid model ID')
    if os.geteuid() != 0:
        parser.error('Run with sudo on the Jobiew server')
    if not ENV_PATH.exists():
        parser.error('Expected /etc/jobiew/jobiew.env; this is not a fresh-install script')
    if args.status:
        state = read_env_flag_status(ENV_PATH.read_text(encoding='utf-8'))
        print('Claude six-axis configuration (secrets hidden):')
        for key, value in state.items():
            print(f'  {key}: {value}')
        return 0

    print('Generate a NEW Anthropic API key and revoke the key shared in chat.')
    print('This script only edits /etc/jobiew/jobiew.env; it does not send a paid request.')
    try:
        key = getpass.getpass('Paste NEW Anthropic API key (hidden): ').strip()
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled; no configuration changed.', file=sys.stderr)
        return 1
    if not KEY_PATTERN.fullmatch(key):
        print('Invalid API key format. No configuration changed.', file=sys.stderr)
        return 1
    settings = {
        'ANTHROPIC_API_KEY': key,
        'JOBIEW_CLAUDE_SIX_ENABLED': '1',
        'JOBIEW_CLAUDE_SIX_LIMIT': str(args.limit),
        'JOBIEW_CLAUDE_SIX_MODEL': args.model,
    }
    backup = update_file(ENV_PATH, settings)
    print('Claude configuration saved; key value was not displayed.')
    print(f'Previous env backup: {backup.name}')
    print('NEXT: sudo systemctl restart jobiew-web')
    print('THEN: sudo python3 /opt/jobiew/scripts/enable_claude_six_v234.py --status')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
