"""Regression tests: Windows must be able to delete the temp source DB after import."""
import sqlite3
import tempfile
from contextlib import closing
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from companies.models import Company
from experiences.models import PublicExperience


class SourceConnectionLifecycleTests(TestCase):
    @staticmethod
    def make_source(path):
        with closing(sqlite3.connect(str(path))) as conn:
            conn.execute("""CREATE TABLE reviews (
                url TEXT, source TEXT, company TEXT, company_url TEXT, title TEXT,
                review_type TEXT, job_title TEXT, published_jalali TEXT,
                employment_period_jalali TEXT, rating_5 REAL, dimension_ratings_json TEXT,
                pros_json TEXT, cons_json TEXT, body TEXT, content_sha256 TEXT,
                crawled_at_utc TEXT
            )""")
            rows = [('https://example.org/w', 'work'), ('https://example.org/i', 'interview')]
            for url, kind in rows:
                conn.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (url, 'test', 'شرکت تست', 'https://example.org/co', 'عنوان', kind,
                     '', None, None, None, '{}', '[]', '[]', 'متن تست', url, '2026-10-19T00:00:00+00:00'))
            conn.commit()

    @staticmethod
    def tracking_context():
        """Return a patched connector and captured actual sqlite connections."""
        original = sqlite3.connect
        opened = []
        def track(*args, **kwargs):
            conn = original(*args, **kwargs)
            opened.append(conn)
            return conn
        return patch('experiences.management.commands.import_crawler_snapshot.sqlite3.connect',
                     side_effect=track), opened

    def assert_all_closed(self, opened):
        self.assertTrue(opened, 'No SQLite connection was tracked')
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')

    def test_import_closes_source_every_time_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / 'src.db'
            self.make_source(src)
            cm, opened = self.tracking_context()
            with cm:
                call_command('import_crawler_snapshot', snapshot=str(src), stdout=StringIO())
                call_command('import_crawler_snapshot', snapshot=str(src), stdout=StringIO())
            self.assert_all_closed(opened)
            self.assertEqual(Company.objects.count(), 1)
            self.assertEqual(PublicExperience.objects.count(), 2)
            company = Company.objects.get()
            self.assertEqual((company.source_work_count, company.source_interview_count), (1, 1))
            # This must also succeed on Windows where open SQLite handles lock src.db.
            src.unlink()
            self.assertFalse(src.exists())

    def test_dry_run_closes_source_on_early_return(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / 'src.db'
            self.make_source(src)
            cm, opened = self.tracking_context()
            with cm:
                call_command('import_crawler_snapshot', snapshot=str(src), dry_run=True, stdout=StringIO())
            self.assert_all_closed(opened)
            self.assertEqual(PublicExperience.objects.count(), 0)
            src.unlink()

    def test_invalid_source_closes_connection_on_error(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / 'src.db'
            with closing(sqlite3.connect(str(src))) as conn:
                conn.execute('CREATE TABLE unrelated (x TEXT)')
                conn.commit()
            cm, opened = self.tracking_context()
            with cm, self.assertRaises(CommandError):
                call_command('import_crawler_snapshot', snapshot=str(src), stdout=StringIO())
            self.assert_all_closed(opened)
            src.unlink()
