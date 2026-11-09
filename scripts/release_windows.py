#!/usr/bin/env python3
"""Package current LOCAL Jobiew code, including uncommitted v2.0.4 changes.

Never package .env, databases, passwords, test logs or crawler data.
No Git or server mutations. Packages only project-owned code directories and the repository-owned Windows crawler runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED

DIRS = ('backend', 'crawler', 'deploy', 'docs', 'scripts', 'tools')
ROOT_FILES = ('README.md', 'requirements.txt', '.env.example', 'Run_Company_Marathon.ps1')
ALLOWED = {'.py', '.html', '.css', '.js', '.json', '.md', '.txt', '.yml', '.yaml',
           '.sh', '.ps1', '.pyz', '.service', '.timer', '.conf', '.toml', '.svg', '.png', '.jpg',
           '.jpeg', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.map'}
EXCLUDE = {'__pycache__', '.git', '.venv', 'venv', 'data', 'reports', 'logs',
           'node_modules', '_patch_backups', '.pytest_cache', '.mypy_cache',
           '.idea', 'media', 'import_staging', 'private', 'secrets', 'locks'}
SUSPICIOUS = {'.env', 'postgres_local.json', 'id_rsa', 'id_ed25519', 'credentials.json'}


def source_files(root: Path):
    for d in DIRS:
        base = root / d
        if not base.is_dir():
            raise RuntimeError(f'Required project directory not found: {base}')
        for path in sorted(base.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(x.lower() in EXCLUDE for x in rel.parts):
                continue
            if path.name.lower() in SUSPICIOUS or path.name.startswith('.env.'):
                continue
            if path.suffix.lower() not in ALLOWED:
                continue
            # Source-controlled assets only. Never include large private crawler output.
            if path.stat().st_size > 40 * 1024**2:
                raise RuntimeError(f'Unusually large source file; inspect before release: {rel}')
            yield path
    for name in ROOT_FILES:
        p = root / name
        if p.is_file():
            yield p


def create_release(root: Path, output: Path):
    root = root.resolve()
    output = output.resolve()
    if not (root / 'backend' / 'manage.py').is_file():
        raise RuntimeError('Root is not the Jobiew project')
    reg = root / 'backend' / 'criteria_v2' / 'registry.py'
    if not reg.is_file():
        raise RuntimeError('Dual 6+6 source missing: criteria_v2 registry')
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    files = list(source_files(root))
    if len(files) < 50:
        raise RuntimeError('Too few source files found; refusing incomplete deploy bundle')
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'format': 'jobiew-local-code-v205',
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'requirements': 'Deploy code; then migrate/collectstatic only after backup and preflight',
                'files': {}}
    tmp = output.with_name(output.name + '.partial')
    try:
        with ZipFile(tmp, 'w', compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for path in files:
                rel = path.relative_to(root).as_posix()
                data = path.read_bytes()
                z.writestr(rel, data)
                manifest['files'][rel] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            z.writestr('release_manifest_v205.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        import os
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return {'status': 'code_release_created', 'path': str(output),
            'files': len(files), 'includes_criteria_v2': True,
            'contains_database_or_crawler_data': False}


def main(argv=None):
    p = argparse.ArgumentParser(description='Archive current local Jobiew source without secrets or DB files')
    p.add_argument('--root', type=Path,
                   default=Path(r'C:\Users\Administrator\PycharmProjects\Jobiew'))
    p.add_argument('--output', type=Path, default=None)
    a = p.parse_args(argv)
    name = 'Jobiew_Code_Release_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.zip'
    output = a.output or Path.home() / 'Downloads' / name
    try:
        print(json.dumps(create_release(a.root, output), ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError) as exc:
        p.exit(2, f'RELEASE_PACKAGING_FAILED: {type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
