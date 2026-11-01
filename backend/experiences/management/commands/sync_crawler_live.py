"""Incrementally synchronize a LIVE crawler SQLite database into Django/PostgreSQL.

Never write to the crawler SQLite file. Snapshot with SQLite's online backup API so
WAL and concurrent crawler commits are handled consistently. The existing importer
owns the mapping and preserves staff review fields.
"""
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from experiences.management.commands.import_crawler_snapshot import identity_from_url
from experiences.models import PublicExperience


def require_postgres_target():
    if connection.vendor != 'postgresql':
        raise CommandError('Refusing sync: Django default database is not PostgreSQL.')


def online_snapshot(src_path, dst_path, max_seconds=180):
    """Read-only source; includes committed WAL changes up to consistent backup point."""
    started = time.monotonic()
    uri = src_path.resolve().as_uri() + '?mode=ro'

    def progress(status, remaining, total):
        if time.monotonic() - started > max_seconds:
            raise TimeoutError('Online SQLite backup exceeded time limit.')

    with closing(sqlite3.connect(uri, uri=True, timeout=10.0)) as src:
        src.execute('PRAGMA busy_timeout=10000')
        with closing(sqlite3.connect(str(dst_path), timeout=10.0)) as dst:
            src.backup(dst, pages=128, progress=progress, sleep=0.1)
            result = dst.execute('PRAGMA quick_check').fetchone()
            if not result or result[0] != 'ok':
                raise ValueError('Online SQLite snapshot failed quick_check.')


def read_source_rows(snapshot):
    """Check source identity and keep only fields needed for post-import verification."""
    data = {}
    total = 0
    work = 0
    interviews = 0
    with closing(sqlite3.connect(snapshot)) as src:
        src.row_factory = sqlite3.Row
        for row in src.execute('SELECT url, review_type, company_url, content_sha256, title, body FROM reviews'):
            total += 1
            url = (row['url'] or '').strip()
            company_url = (row['company_url'] or '').strip()
            kind = row['review_type']
            if not url.startswith(('https://', 'http://')) or not company_url.startswith(('https://', 'http://')) or kind not in {'work', 'interview'}:
                raise ValueError(f'Invalid source identity at row {total}; refusing partial import.')
            if url in data:
                raise ValueError('Duplicate source review URLs detected; refusing ambiguous import.')
            data[url] = (str(row['content_sha256'] or ''), kind, identity_from_url(company_url),
                         row['title'] or '', row['body'] or '')
            if kind == 'work':
                work += 1
            else:
                interviews += 1
    return data, {'source_rows': total, 'work': work, 'interview': interviews}


def compare_target(source_data):
    """Compare review provenance and body; do not confuse with all-site totals."""
    missing = []
    differing = []
    protected = []
    urls = list(source_data)
    for start in range(0, len(urls), 400):
        subset = urls[start:start + 400]
        observed = {row['source_url']: row for row in PublicExperience.objects.filter(
            source_url__in=subset).values('source_url', 'content_sha256', 'source_kind',
                                            'company_id', 'title', 'body', 'published_publicly')}
        for url in subset:
            row = observed.get(url)
            if not row:
                missing.append(url)
                continue
            expected = source_data[url]
            current = (row['content_sha256'], row['source_kind'], row['company_id'],
                       row['title'], row['body'])
            if current != expected:
                differing.append(url)
                if row['published_publicly']:
                    protected.append(url)
    return {'missing': missing, 'differing': differing, 'protected_published': protected}


def approved_ai_on_changed(urls):
    if not urls:
        return 0
    from assessments.models import AiAssessment
    return AiAssessment.objects.filter(experience__source_url__in=urls, publish_approved=True).count()


def acquire_local_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CommandError(f'Another synchronization may be running. Check lock: {path}') from exc
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'pid': os.getpid(), 'created_at_utc': datetime.now(timezone.utc).isoformat()}))
    except Exception:
        path.unlink(missing_ok=True)
        raise


def store_report(report_dir, report, *, applied):
    report_dir.mkdir(parents=True, exist_ok=True)
    # Do not include passwords or full review bodies in reports.
    filename = ('applied' if applied else 'preview') + '_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'
    data = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    target = report_dir / filename
    with tempfile.NamedTemporaryFile(mode='w', dir=report_dir, encoding='utf-8', delete=False) as f:
        tmp = Path(f.name)
        f.write(data)
    try:
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


class Command(BaseCommand):
    help = 'Create an online snapshot of the live crawler SQLite DB, then incrementally sync into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--source', type=str, default=None, help='Live crawler SQLite database path.')
        parser.add_argument('--apply', action='store_true', help='Perform PostgreSQL import (default is read-only preview).')
        parser.add_argument('--backup-timeout', type=int, default=180)
        parser.add_argument('--report-dir', type=str, default=None)

    def handle(self, *args, **options):
        require_postgres_target()
        base = Path(settings.BASE_DIR).resolve()
        live = Path(options['source'] or base.parent / 'tajrobewiki_crawler' / 'data' / 'tajrobewiki.db').resolve()
        if not live.is_file():
            raise CommandError(f'Crawler SQLite file not found: {live}; pass --source explicitly.')
        if live == (base / 'db.sqlite3').resolve():
            raise CommandError('Refusing to treat Django legacy SQLite as live crawler database.')
        if options['backup_timeout'] < 1:
            raise CommandError('--backup-timeout must be positive')
        runtime = Path(os.environ.get('JOBIEW_RUNTIME_DIR') or base).resolve()
        report_dir = Path(options['report_dir'] or runtime / 'reports' / 'crawler_sync_v34').resolve()
        lock = runtime / 'locks' / 'crawler_sync_v34.lock'
        acquire_local_lock(lock)
        try:
            staging = runtime / 'import_staging'
            staging.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='wi_sync_', dir=staging) as temp:
                snapshot = Path(temp) / 'crawler_consistent_snapshot.sqlite3'
                try:
                    online_snapshot(live, snapshot, max_seconds=options['backup_timeout'])
                    source_data, source_counts = read_source_rows(snapshot)
                except (sqlite3.Error, ValueError, TimeoutError) as exc:
                    raise CommandError(f'Crawler source snapshot cannot be validated: {type(exc).__name__}: {exc}') from exc
                before = compare_target(source_data)
                report = {
                    'version': 'v0.34', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'source': str(live), 'django_database_engine': connection.vendor,
                    'django_database_name': str(connection.settings_dict.get('NAME')),
                    'snapshot_check': 'ok', **source_counts,
                    'before': {k: len(v) for k, v in before.items()},
                    'apply_requested': bool(options['apply']),
                    'no_claude_requests': True, 'crawler_database_read_only': True,
                }
                if not options['apply']:
                    report['status'] = 'preview_only_no_database_changes'
                    filename = store_report(report_dir, report, applied=False)
                    self.stdout.write(json.dumps({**report, 'report': str(filename)}, ensure_ascii=False))
                    return
                if before['protected_published'] or approved_ai_on_changed(before['differing']):
                    raise CommandError('Source changes affect already-published content or approved AI assessments. '
                                       'Import stopped; review those records before continuing.')
                with transaction.atomic():
                    output = StringIO()
                    call_command('import_crawler_snapshot', snapshot=str(snapshot), stdout=output)
                    try:
                        imported = json.loads(output.getvalue().strip().splitlines()[-1])
                    except (IndexError, ValueError) as exc:
                        raise CommandError('Existing source importer did not provide a valid summary; import rolled back.') from exc
                    after = compare_target(source_data)
                    if after['missing'] or after['differing']:
                        raise CommandError('PostgreSQL does not exactly match the source URLs, content hashes and text; import rolled back. '
                                           f'Missing={len(after["missing"])} differing={len(after["differing"])}.')
                    if imported['source_rows'] != source_counts['source_rows'] or imported['skipped']:
                        raise CommandError('Source importer row counts disagree; import rolled back.')
                    report['import_result'] = {k: imported[k] for k in (
                        'source_rows', 'new_companies', 'new_experiences',
                        'updated_experiences', 'unchanged_experiences', 'skipped', 'work', 'interview')}
                    report['after'] = {k: len(v) for k, v in after.items()}
                report['status'] = 'committed_and_verified'
                filename = store_report(report_dir, report, applied=True)
                self.stdout.write(json.dumps({**report, 'report': str(filename)}, ensure_ascii=False))
        finally:
            lock.unlink(missing_ok=True)
