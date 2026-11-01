#!/usr/bin/env python3
"""Offline release verification that never contacts the network or database."""
from pathlib import Path
import ast
import json
import sys
ROOT=Path(__file__).resolve().parents[1]

def run():
    errors=[]; pyfiles=list(ROOT.rglob('*.py'))
    for p in pyfiles:
        try: ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
        except Exception as e: errors.append(f'{p.relative_to(ROOT)}: {e}')
    must=[ROOT/'.gitignore',ROOT/'.env.example',ROOT/'backend/manage.py',ROOT/'backend/workplace_insights/settings.py',
          ROOT/'backend/experiences/management/commands/sync_crawler_live.py',ROOT/'crawler/crawl_site.py',
          ROOT/'deploy/systemd/jobiew-web.service',ROOT/'deploy/systemd/jobiew-ingest.timer']
    for p in must:
        if not p.exists(): errors.append(f'Missing: {p.relative_to(ROOT)}')
    for p in ROOT.rglob('*'):
        if p.is_file() and (p.name in {'.env','db.sqlite3','postgres_local.json'} or p.suffix in {'.db','.dump','.sqlite3'}):
            errors.append(f'Private or DB file in release: {p.relative_to(ROOT)}')
    report={'status':'OK' if not errors else 'FAIL','python_files':len(pyfiles),'errors':errors,'database_tests_run':False}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not errors else 1
if __name__=='__main__':sys.exit(run())
