#!/usr/bin/env python3
"""Jobiew one-shot crawler -> PostgreSQL pipeline for a systemd timer.

One shared on-disk SQLite crawler store remains private under JOBIEW_RUNTIME_DIR.
Django's sync command takes a consistent, READ-ONLY online SQLite snapshot and
atomically upserts source reviews into PostgreSQL. No AI scoring or publishing.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
CRAWLER = ROOT / 'crawler' / 'crawl_site.py'


def setting_int(name, default, minimum=1, maximum=10000):
    raw = os.environ.get(name, str(default))
    try:
        val = int(raw)
    except ValueError as exc:
        raise ValueError(f'{name} must be an integer') from exc
    if not minimum <= val <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return val


def command_plan(mode, runtime):
    db = runtime / 'data' / 'tajrobewiki.db'
    crawler = [sys.executable, str(CRAWLER), '--scope', 'experiences',
        '--db', str(db), '--failures', str(runtime/'data'/'failed_requests.jsonl'),
        '--max-items', str(setting_int('JOBIEW_CRAWL_MAX_ITEMS', 50, 1, 1000)),
        '--max-requests', str(setting_int('JOBIEW_CRAWL_MAX_REQUESTS', 90, 1, 2000)),
        '--pause', str(setting_int('JOBIEW_CRAWL_PAUSE_SECONDS', 12, 3, 120)),
        '--permission-confirmed']
    sync = [sys.executable, str(BACKEND/'manage.py'), 'sync_crawler_live',
            '--source', str(db), '--report-dir', str(runtime/'reports'/'crawler_sync_v34')]
    if mode != 'preview':
        sync.append('--apply')
    return [(crawler, runtime), (sync, BACKEND)] if mode == 'crawl-and-sync' else [(sync, BACKEND)]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Jobiew crawler and server PostgreSQL sync')
    parser.add_argument('--mode', choices=['crawl-and-sync', 'sync-only', 'preview'], default='crawl-and-sync')
    parser.add_argument('--show-plan', action='store_true', help='no crawl, no DB connection or writes')
    args = parser.parse_args(argv)
    runtime = Path(os.environ.get('JOBIEW_RUNTIME_DIR', '/var/lib/jobiew')).resolve()
    try:
        plan = command_plan(args.mode, runtime)
        if args.show_plan:
            print(json.dumps({'mode':args.mode,'runtime':str(runtime),
                'steps':[[str(p) for p in step] for step,_ in plan], 'executed': False}, ensure_ascii=False))
            return 0
        if args.mode == 'crawl-and-sync' and os.environ.get('JOBIEW_CRAWLER_PERMISSION_CONFIRMED') != '1':
            print('STOP: JOBIEW_CRAWLER_PERMISSION_CONFIRMED=1 is required after authorization.',file=sys.stderr)
            return 2
        if os.environ.get('WI_DB_ENGINE', '').lower() != 'postgresql':
            print('STOP: set WI_DB_ENGINE=postgresql to sync ONLY to the server PostgreSQL DB.',file=sys.stderr)
            return 2
        (runtime/'data').mkdir(parents=True,exist_ok=True)
        (runtime/'reports').mkdir(parents=True,exist_ok=True)
        for cmd,cwd in plan:
            print('JOBIEW_STEP', 'crawler' if cwd==runtime else 'postgres_sync',flush=True)
            # No shell invocation, inherit process environment from protected systemd EnvironmentFile.
            subprocess.run(cmd, cwd=str(cwd), check=True)
        print(json.dumps({'status':'pipeline_finished','mode':args.mode,
             'note':'Source data sync only; AI assessments are not auto-generated.'}))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'JOBIEW_PIPELINE_FAILED: {type(exc).__name__}',file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
