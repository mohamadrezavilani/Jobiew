"""TajrobeWiki 48-hour checkpointed runner for an already installed crawler.

No browser, account automation or policy bypass. Runs the existing crawler
sequentially; waits through transient outages; stops on access restrictions,
unrecognized page structure, or data-integrity problems.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.parse import quote

EXPECTED_HASH = '50a459b0a2f7cc2a7ed1c7ce26751bf1070278dc76638873d7119f2bc4ee6480'
RETRYABLE = ('connectionerror', 'remotedisconnected', 'connecttimeout', 'readtimeout',
             'connectionreset', 'connection aborted', 'timed out', 'temporaryfetcherror',
             'http 500', 'http 502', 'http 503', 'http 504', 'server disconnected')
POLICY = ('http 403', 'http 429', '403 forbidden', '429 too many requests',
          'disallowed by robots', 'robots exclusion', 'access denied', 'captcha',
          'permission denied by site', 'login required', 'verification required')
PARSER_HALT = ('consecutive unexpected pages', 'unrecognized company html (2 consecutive)',
               'unrecognized listing page', 'has no recognizable links')
STORAGE_HALT = ('database write failed', 'database disk image is malformed',
                'disk i/o error', 'database or disk is full', 'database is locked')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for buf in iter(lambda: f.read(1024 * 1024), b''):
            h.update(buf)
    return h.hexdigest()


def atomic_json(path, obj):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write_event(path, record):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


@contextmanager
def ro_db(path):
    uri = 'file:' + quote(str(path.resolve()).replace('\\', '/'), safe='/:') + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        yield con
    finally:
        con.close()


def snapshot(path):
    with ro_db(path) as con:
        rows = {t: con.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                for t in ('reviews', 'company_profiles', 'blog_articles')}
        queue = {f'{kind}_{status}': count for kind, status, count in con.execute(
            'SELECT kind,status,count(*) FROM site_queue GROUP BY kind,status')}
        listings = {name: {'next_page': nxt, 'last_page': last, 'complete': bool(done)}
                    for name, nxt, last, done in con.execute(
                        'SELECT section,next_page,last_page,completed FROM site_listings')}
    return {'rows': rows, 'queue': queue, 'listings': listings}


def verified_root(root):
    source = root / 'crawl_site.py'
    db = root / 'data' / 'tajrobewiki.db'
    if not source.is_file() or not db.is_file():
        raise RuntimeError('Run from tajrobewiki_crawler folder; crawl_site.py or SQLite is missing')
    actual = sha(source)
    if actual != EXPECTED_HASH:
        raise RuntimeError('crawl_site.py differs from reviewed v3. Found sha256 ' + actual +
                           '; expected ' + EXPECTED_HASH + '. Refusing to change existing code.')
    return db


@contextmanager
def exclusive_lock(path):
    """OS-level lock released if process crashes; works on Windows and Unix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            if handle.tell() == 0:
                handle.write(b' ')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('Another v7 runner already holds the lock') from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Another v7 runner already holds the lock') from exc
        yield
    finally:
        if os.name == 'nt':
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def make_backup(db, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db), timeout=45) as source, sqlite3.connect(str(target)) as dest:
        source.backup(dest)
    with sqlite3.connect(str(target), timeout=30) as con:
        integrity = con.execute('PRAGMA quick_check').fetchone()[0]
    if integrity != 'ok':
        raise RuntimeError('SQLite backup failed integrity check; aborting')


def init_ledger(path):
    con = sqlite3.connect(path, timeout=40)
    con.execute('''CREATE TABLE IF NOT EXISTS retry_ledger (
        url TEXT PRIMARY KEY, category TEXT NOT NULL, attempts INTEGER NOT NULL,
        last_requeue REAL NOT NULL, next_eligible REAL NOT NULL,
        previous_error TEXT NOT NULL)''')
    con.commit()
    return con


def retry_category(error):
    e = (error or '').casefold()
    if any(s in e for s in POLICY):
        return None
    if any(x in e for x in RETRYABLE):
        return 'transient'
    if 'heading h1' in e or 'page has no heading h1' in e:
        return 'legacy_parser'
    return None


def choose_requeues(main, ledger, now, legacy_limit, transient_limit, max_transient):
    """Prepare a bounded set of eligible old failures, no actual changes."""
    accepted = []
    allowance = {'legacy_parser': legacy_limit, 'transient': transient_limit}
    # Read only failed entries, not a blanket retry of 2,000+ historical errors.
    for url, error in main.execute('''SELECT url,last_error FROM site_queue
                                     WHERE kind='company' AND status='failed'
                                     ORDER BY updated_utc, rowid'''):
        kind = retry_category(error)
        if kind is None or allowance[kind] <= 0:
            continue
        rec = ledger.execute('SELECT attempts,next_eligible FROM retry_ledger WHERE url=?', (url,)).fetchone()
        tries, eligible = rec if rec else (0, 0)
        if kind == 'legacy_parser' and tries >= 1:
            continue
        if kind == 'transient' and (tries >= max_transient or now < eligible):
            continue
        accepted.append((url, error or '', kind, tries + 1))
        allowance[kind] -= 1
        if all(n == 0 for n in allowance.values()):
            break
    return accepted


def requeue_failed(db, ledger, audit, old_limit, transient_limit, max_transient):
    """Retain original errors in audit before changing queue; never retry 403/429."""
    if not old_limit and not transient_limit:
        return {'legacy_parser': 0, 'transient': 0}
    now = time.time()
    counts = {'legacy_parser': 0, 'transient': 0}
    with sqlite3.connect(str(db), timeout=45) as main:
        chosen = choose_requeues(main, ledger, now, old_limit, transient_limit, max_transient)
        if not chosen:
            return counts
        # Append a durable undo/audit record before any queue status update.
        for url, original, kind, number in chosen:
            write_event(audit, {'at_utc': utc_now(), 'url': url, 'prior_error': original,
                                'retry_kind': kind, 'attempt': number})
        main.execute('BEGIN IMMEDIATE')
        for url, original, kind, number in chosen:
            cur = main.execute('''UPDATE site_queue SET status='pending', last_error=NULL,
                                  updated_utc=? WHERE url=? AND kind='company'
                                  AND status='failed' AND last_error=?''',
                               (utc_now(), url, original))
            if not cur.rowcount:
                continue
            wait = min(12 * 3600, 20 * 60 * (3 ** (number - 1)))
            ledger.execute('''INSERT INTO retry_ledger(url, category, attempts,
                              last_requeue, next_eligible, previous_error) VALUES (?,?,?,?,?,?)
                              ON CONFLICT(url) DO UPDATE SET category=excluded.category,
                              attempts=excluded.attempts,last_requeue=excluded.last_requeue,
                              next_eligible=excluded.next_eligible, previous_error=excluded.previous_error''',
                           (url, kind, number, now, now + wait, original))
            counts[kind] += 1
        main.commit()
        ledger.commit()
    return counts


def classify_log(content, rc, timed_out=False):
    low = content.casefold()
    if any(x in low for x in POLICY):
        return 'access_or_rate_limit'
    if any(x in low for x in STORAGE_HALT):
        return 'storage_error'
    if any(x in low for x in PARSER_HALT):
        return 'unexpected_html'
    if 'cannot verify robots policy' in low:
        return 'robots_unavailable'
    if timed_out:
        return 'worker_timeout'
    if 'too many consecutive errors' in low or 'listing unavailable' in low:
        return 'network_outage'
    if rc != 0:
        return 'worker_error'
    # A subprocess returning 0 can have caught an internal halt; detect it.
    if 'stopped by access/policy/sustained failures' in low:
        return 'other_crawler_halt'
    return 'ok'


def select_python(root):
    """Pick a known working environment from the local projects. No installs."""
    candidates = [
        root / '.venv' / 'Scripts' / 'python.exe',
        root.parent / 'workplace_insights' / '.venv' / 'Scripts' / 'python.exe',
        root / '.venv' / 'bin' / 'python',
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            check = subprocess.run([str(candidate), '-c', 'import bs4, requests'],
                                   capture_output=True, timeout=15)
            if check.returncode == 0:
                return str(candidate)
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError('No available Python interpreter with bs4 and requests; activate the crawler environment')


def execute_cycle(root, args, logfile, heartbeat=None):
    cmd = [args.python_exe, '-u', 'crawl_site.py', '--scope', 'companies',
           '--permission-confirmed', '--max-items', str(args.batch_size),
           '--max-requests', str(args.batch_size + args.request_slack),
           '--pause', str(args.pause), '--retries', str(args.retries),
           '--retry-wait', str(args.retry_wait), '--max-consecutive-errors', '2',
           '--max-consecutive-parse-errors', '2']
    started = time.monotonic()
    last_heartbeat = started
    with logfile.open('w', encoding='utf-8') as file:
        worker = subprocess.Popen(cmd, cwd=str(root), stdout=file, stderr=subprocess.STDOUT)
        timed_out = False
        try:
            while worker.poll() is None:
                if heartbeat is not None and time.monotonic() - last_heartbeat >= 30:
                    heartbeat()
                    last_heartbeat = time.monotonic()
                if time.monotonic() - started > args.worker_timeout_minutes * 60:
                    timed_out = True
                    worker.terminate()
                    try:
                        worker.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait()
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()
            raise
    text = logfile.read_text(encoding='utf-8', errors='replace')
    return {'worker_return_code': worker.returncode, 'classification': classify_log(text, worker.returncode, timed_out),
            'runtime_seconds': round(time.monotonic() - started),
            'temporary_warning_count': len(re.findall('temporary (?:fetch )?error', text, re.I)),
            'log': str(logfile)}


def sleep_until(seconds, state, statefile, reason):
    """Sleep in small slices, heartbeat persists so status works while waiting."""
    state['mode'] = 'cooldown'
    state['last_event'] = reason
    state['next_attempt_utc'] = datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat()
    atomic_json(statefile, state)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(min(15, max(.01, end - time.monotonic())))
        if time.monotonic() + 1 >= end:
            break
        # Lightweight status update every minute rather than in each slice.
        if int(time.monotonic()) % 60 < 15:
            state['heartbeat_utc'] = utc_now()
            atomic_json(statefile, state)


def run(root, db, args):
    dest = root / 'reports' / 'company_marathon_v7'
    dest.mkdir(parents=True, exist_ok=True)
    statefile, ledgerfile, events = dest / 'status.json', dest / 'retry_ledger.sqlite3', dest / 'events.jsonl'
    with exclusive_lock(dest / 'runner.lock'):
        state = read_json(statefile, {})
        now = time.time()
        if state.get('mode') in ('running', 'cooldown', 'interrupted') and state.get('deadline_ts', 0) > now:
            print('RESUMING previous 48-hour window; deadline is unchanged.', flush=True)
        else:
            state = {'started_utc': utc_now(), 'start_ts': now,
                     'deadline_ts': now + args.hours * 3600,
                     'deadline_utc': datetime.fromtimestamp(now + args.hours*3600, timezone.utc).isoformat(),
                     'cycles': 0, 'profiles_at_start': snapshot(db)['rows']['company_profiles'],
                     'last_backup_ts': 0, 'outcome': None}
        state['mode'] = 'running'
        state['heartbeat_utc'] = utc_now()
        atomic_json(statefile, state)
        ledger = init_ledger(ledgerfile)
        outage_streak = 0
        last_reason = 'time_limit'
        try:
            backup_root = root / '_patch_backups' / 'company_marathon_v7'
            backup = backup_root / ('db_' + stamp() + '.sqlite3')
            make_backup(db, backup)
            state['last_backup_ts'] = time.time()
            state['last_backup'] = str(backup)
            atomic_json(statefile, state)
            print('BACKUP:', backup, flush=True)
            while time.time() < state['deadline_ts']:
                before = snapshot(db)
                listing = before['listings'].get('companies', {})
                if listing.get('complete') and not before['queue'].get('company_pending', 0):
                    # Still permit a finite pass over historical parser failures.
                    if args.recover_legacy == 0 and args.recover_transient == 0:
                        last_reason = 'listings_complete'; break
                if time.time() - state.get('last_backup_ts', 0) >= args.backup_every_hours*3600:
                    backup = backup_root / ('db_' + stamp() + '.sqlite3')
                    make_backup(db, backup)
                    state['last_backup_ts'] = time.time()
                    state['last_backup'] = str(backup)
                    atomic_json(statefile, state)
                    print('BACKUP:', backup, flush=True)
                # Queue small numbers of previously failed company pages.
                recovered = requeue_failed(db, ledger, events, args.recover_legacy,
                                           args.recover_transient, args.max_transient_requeues)
                state['cycles'] += 1
                cycle = state['cycles']
                state['mode'] = 'running'
                state['heartbeat_utc'] = utc_now()
                state['last_event'] = f'cycle {cycle} started'
                atomic_json(statefile, state)
                logfile = dest / (f'cycle_{cycle:06d}_{stamp()}.log')
                def update_heartbeat():
                    state['heartbeat_utc'] = utc_now()
                    atomic_json(statefile, state)
                worker = execute_cycle(root, args, logfile, update_heartbeat)
                after = snapshot(db)
                difference = after['rows']['company_profiles'] - before['rows']['company_profiles']
                page_before = listing.get('next_page')
                page_after = after['listings'].get('companies', {}).get('next_page')
                progressed = difference > 0 or (page_before is not None and page_after != page_before)
                event = {'at_utc': utc_now(), 'cycle': cycle, 'new_profiles': difference,
                         'total_profiles': after['rows']['company_profiles'],
                         'page': page_after, 'total_pages': after['listings'].get('companies', {}).get('last_page'),
                         'pending': after['queue'].get('company_pending', 0),
                         'failed': after['queue'].get('company_failed', 0),
                         'requeued': recovered, **worker}
                write_event(events, event)
                state['last_cycle'] = event
                state['heartbeat_utc'] = utc_now()
                atomic_json(statefile, state)
                print(f"[{utc_now()}] cycle={cycle} +{difference} profiles={event['total_profiles']} "
                      f"page={page_after}/{event['total_pages']} "
                      f"kind={worker['classification']} warnings={worker['temporary_warning_count']}", flush=True)
                reason = worker['classification']
                if reason in ('access_or_rate_limit', 'storage_error', 'unexpected_html'):
                    last_reason = reason
                    print('SAFETY STOP:', reason, '; inspect ', logfile, flush=True)
                    break
                if reason == 'ok' and progressed:
                    outage_streak = 0
                    delay = args.cooldown_seconds
                else:
                    outage_streak += 1
                    delay = min(args.max_backoff_minutes * 60,
                                args.cooldown_seconds * (2 ** min(outage_streak, 8)))
                    print(f'Server slow/unstable or no progress; resting {delay/60:.1f} min.', flush=True)
                if after['listings'].get('companies', {}).get('complete') and not after['queue'].get('company_pending', 0):
                    # If there are no eligible old errors left (or we've exhausted retry budget), finish.
                    with sqlite3.connect(str(db), timeout=30) as check:
                        left = choose_requeues(check, ledger, time.time(),
                                               args.recover_legacy, args.recover_transient,
                                               args.max_transient_requeues)
                    if not left:
                        last_reason = 'all_discovered_company_pages_processed'; break
                if time.time() + delay >= state['deadline_ts']:
                    last_reason = 'time_limit'; break
                sleep_until(delay, state, statefile, 'cooldown after cycle ' + str(cycle))
            else:
                last_reason = 'time_limit'
        except KeyboardInterrupt:
            last_reason = 'interrupted'
            print('Interrupted by operator; all checkpoints retained.', flush=True)
        except Exception as e:
            last_reason = 'runner_fault'
            print('RUNNER ERROR:', repr(e), flush=True)
            write_event(events, {'at_utc': utc_now(), 'kind': 'runner_fault', 'error': repr(e)})
        finally:
            ledger.close()
            state['mode'] = 'interrupted' if last_reason == 'interrupted' else 'ended'
            state['outcome'] = last_reason
            state['finished_utc'] = utc_now()
            state['final_snapshot'] = snapshot(db)
            atomic_json(statefile, state)
            summary_path = dest / ('final_summary_' + stamp() + '.json')
            atomic_json(summary_path, state)
            print('FINAL REPORT:', summary_path, flush=True)
            print('OUTCOME:', last_reason, flush=True)
        return 0 if last_reason in ('time_limit', 'listings_complete', 'all_discovered_company_pages_processed', 'interrupted') else 2


def main(argv=None):
    p = argparse.ArgumentParser(description='TajrobeWiki two-day sequential resilient company crawler runner v7')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--status', action='store_true')
    p.add_argument('--project-root', type=Path, default=Path.cwd())
    p.add_argument('--hours', type=float, default=48)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--request-slack', type=int, default=6)
    p.add_argument('--pause', type=float, default=35)
    p.add_argument('--retries', type=int, default=1)
    p.add_argument('--retry-wait', type=float, default=90)
    p.add_argument('--cooldown-seconds', type=int, default=150)
    p.add_argument('--max-backoff-minutes', type=int, default=60)
    p.add_argument('--worker-timeout-minutes', type=int, default=90)
    p.add_argument('--recover-legacy', type=int, default=4)
    p.add_argument('--recover-transient', type=int, default=2)
    p.add_argument('--max-transient-requeues', type=int, default=4)
    p.add_argument('--backup-every-hours', type=int, default=24)
    p.add_argument('--permission-confirmed', action='store_true')
    args = p.parse_args(argv)
    if not .1 <= args.hours <= 168 or not 1 <= args.batch_size <= 12 or not 0 <= args.request_slack <= 10:
        p.error('hours 0.1..168, batch-size 1..12, request-slack 0..10')
    if args.pause < 30 or args.retries not in (0, 1, 2) or args.retry_wait < 60:
        p.error('pause>=30, retries=0..2, retry-wait>=60')
    if not 60 <= args.cooldown_seconds <= 3600 or not 5 <= args.max_backoff_minutes <= 180:
        p.error('cooldown 60..3600, max-backoff-minutes 5..180')
    if not 15 <= args.worker_timeout_minutes <= 180 or not 0 <= args.recover_legacy <= 8:
        p.error('worker timeout 15..180, recover-legacy 0..8')
    if not 0 <= args.recover_transient <= 8 or not 1 <= args.max_transient_requeues <= 10:
        p.error('recover-transient 0..8, max-transient-requeues 1..10')
    if not 1 <= args.backup_every_hours <= 48:
        p.error('backup-every-hours 1..48')
    root = args.project_root.resolve()
    try:
        db = verified_root(root)
    except RuntimeError as exc:
        p.error(str(exc))
    out = root / 'reports' / 'company_marathon_v7'
    if args.status:
        print(json.dumps({'database': snapshot(db), 'runner': read_json(out / 'status.json', {})},
                         ensure_ascii=False, indent=2))
        return 0
    if not args.permission_confirmed:
        p.error('--run requires --permission-confirmed; ensure independent right to collect and reuse public content')
    try:
        args.python_exe = select_python(root)
        print('CRAWLER PYTHON:', args.python_exe, flush=True)
        return run(root, db, args)
    except RuntimeError as exc:
        print('REFUSED:', str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
