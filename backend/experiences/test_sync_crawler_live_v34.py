"""Tests use Django's temporary SQLite test DB; production command requires PostgreSQL."""
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from assessments.models import AiAssessment
from experiences.models import PublicExperience
from experiences.management.commands.sync_crawler_live import online_snapshot, read_source_rows


FIELDS = '''CREATE TABLE reviews (
 url TEXT, source TEXT, company TEXT, company_url TEXT, title TEXT,
 review_type TEXT, job_title TEXT, published_jalali TEXT, employment_period_jalali TEXT,
 rating_5 REAL, dimension_ratings_json TEXT, pros_json TEXT, cons_json TEXT,
 body TEXT, content_sha256 TEXT, crawled_at_utc TEXT
)'''


def add_review(conn, suffix='1', body='متن تجربهٔ کارمند'):
    url = f'https://example.org/review/{suffix}'
    content_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    conn.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
        url, 'tajrobewiki.com', 'شرکت آزمایش', 'https://example.org/company',
        'عنوان نظر', 'work', '', '۱۴۰۵', '', None, '{}', '["نکته مثبت"]', '[]',
        body, content_hash, '2026-10-19T00:00:00+00:00'))
    return url


class SyncLiveTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'live.db'
        with closing(sqlite3.connect(self.source)) as db:
            db.execute(FIELDS)
            self.url = add_review(db)
            db.commit()
        self.override = override_settings(BASE_DIR=self.base)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.reportdir = self.base / 'reports'

    def execute_sync(self, apply=False):
        stdout = StringIO()
        # The guard is intentionally bypassed ONLY in the test suite.
        with patch('experiences.management.commands.sync_crawler_live.require_postgres_target'):
            call_command('sync_crawler_live', source=str(self.source),
                         report_dir=str(self.reportdir), apply=apply, stdout=stdout)
        return json.loads(stdout.getvalue().strip())

    def test_preview_does_not_write_and_removes_temp_snapshot(self):
        result = self.execute_sync()
        self.assertEqual(result['status'], 'preview_only_no_database_changes')
        self.assertEqual(result['source_rows'], 1)
        self.assertEqual(result['before']['missing'], 1)
        self.assertEqual(PublicExperience.objects.count(), 0)
        self.assertFalse((self.base / 'data' / 'crawler_sync_v34.lock').exists())
        self.assertFalse(list((self.base / 'import_staging').glob('wi_sync_*')))

    def test_apply_idempotent_preserves_moderation_and_updates_changed_content(self):
        first = self.execute_sync(apply=True)
        self.assertEqual(first['status'], 'committed_and_verified')
        self.assertEqual(first['import_result']['new_experiences'], 1)
        second = self.execute_sync(apply=True)
        self.assertEqual(second['import_result']['new_experiences'], 0)
        self.assertEqual(second['import_result']['unchanged_experiences'], 1)
        obj = PublicExperience.objects.get(source_url=self.url)
        obj.copyright_review = 'approved'
        obj.company_attribution_status = 'verified'
        obj.save(update_fields=['copyright_review', 'company_attribution_status'])
        with closing(sqlite3.connect(self.source)) as src:
            body = 'متن جدید تجربهٔ کارمند'
            src.execute('UPDATE reviews SET body=?, content_sha256=?',
                        (body, hashlib.sha256(body.encode('utf-8')).hexdigest()))
            src.commit()
        third = self.execute_sync(apply=True)
        self.assertEqual(third['import_result']['updated_experiences'], 1)
        obj.refresh_from_db()
        self.assertEqual(obj.body, body)
        self.assertEqual(obj.copyright_review, 'approved')
        self.assertEqual(obj.company_attribution_status, 'verified')
        self.assertEqual(PublicExperience.objects.count(), 1)

    def test_published_changes_are_blocked(self):
        self.execute_sync(apply=True)
        obj = PublicExperience.objects.get(source_url=self.url)
        obj.published_publicly = True
        obj.save(update_fields=['published_publicly'])
        with closing(sqlite3.connect(self.source)) as src:
            src.execute('UPDATE reviews SET body=?, content_sha256=?', ('تغییر', 'newhash'))
            src.commit()
        with self.assertRaisesRegex(CommandError, 'published'):
            self.execute_sync(apply=True)
        obj.refresh_from_db()
        self.assertNotEqual(obj.body, 'تغییر')

    def test_approved_ai_changes_are_blocked(self):
        self.execute_sync(apply=True)
        obj = PublicExperience.objects.get(source_url=self.url)
        AiAssessment.objects.create(experience=obj, model_name='local', prompt_version='test',
                                    run_id='one', publish_approved=True)
        with closing(sqlite3.connect(self.source)) as src:
            src.execute('UPDATE reviews SET body=?, content_sha256=?', ('تغییر', 'newhash'))
            src.commit()
        with self.assertRaisesRegex(CommandError, 'approved AI'):
            self.execute_sync(apply=True)

    def test_rejects_duplicate_source_urls_and_cleans_snapshot(self):
        with closing(sqlite3.connect(self.source)) as src:
            add_review(src)
            src.commit()
        with self.assertRaisesRegex(CommandError, 'Duplicate'):
            self.execute_sync(apply=True)
        self.assertEqual(PublicExperience.objects.count(), 0)
        self.assertFalse((self.base / 'data' / 'crawler_sync_v34.lock').exists())

    def test_online_backup_reads_wal_and_keeps_live_source_open(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            add_review(writer, '2', 'تجربه دوم')
            writer.commit()
            copied = self.base / 'copied.sqlite3'
            online_snapshot(self.source, copied)
            records, counts = read_source_rows(copied)
            self.assertEqual(counts['source_rows'], 2)
            self.assertIn('https://example.org/review/2', records)
            self.assertEqual(writer.execute('SELECT count(*) FROM reviews').fetchone()[0], 2)
        # The copied source is independent and can be removed after closing all connections.
        copied.unlink()
        self.assertFalse(copied.exists())

    def test_refuses_sqlite_target_without_test_bypass(self):
        # Django may run its *test* database on PostgreSQL after migration.
        # Simulate SQLite explicitly so this guard test is backend-independent.
        from types import SimpleNamespace
        with patch('experiences.management.commands.sync_crawler_live.connection',
                   SimpleNamespace(vendor='sqlite')):
            with self.assertRaisesRegex(CommandError, 'not PostgreSQL'):
                call_command('sync_crawler_live', source=str(self.source), stdout=StringIO())

    def test_postgres_guard_accepts_postgresql_only(self):
        from types import SimpleNamespace
        from experiences.management.commands.sync_crawler_live import require_postgres_target
        for vendor in ('sqlite', 'mysql', 'oracle'):
            with self.subTest(vendor=vendor):
                with patch('experiences.management.commands.sync_crawler_live.connection',
                           SimpleNamespace(vendor=vendor)):
                    with self.assertRaisesRegex(CommandError, 'not PostgreSQL'):
                        require_postgres_target()
        with patch('experiences.management.commands.sync_crawler_live.connection',
                   SimpleNamespace(vendor='postgresql')):
            require_postgres_target()  # No exception. No network or DB writes.
