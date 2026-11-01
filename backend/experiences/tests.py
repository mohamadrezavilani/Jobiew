import sqlite3
import tempfile
from pathlib import Path
from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from companies.models import Company
from experiences.models import PublicExperience

class ImportTests(TestCase):
    def test_idempotent_work_and_interview(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'src.db';c=sqlite3.connect(p)
            c.executescript('CREATE TABLE reviews (url TEXT,source TEXT,company TEXT,company_url TEXT,title TEXT,review_type TEXT,job_title TEXT,published_jalali TEXT,employment_period_jalali TEXT,rating_5 REAL,dimension_ratings_json TEXT,pros_json TEXT,cons_json TEXT,body TEXT,content_sha256 TEXT,crawled_at_utc TEXT);')
            records=[('https://example.org/a','work'),('https://example.org/b','interview')]
            for url,kind in records:
                c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(url,'test','شرکت','https://example.org/co','عنوان',kind,'',None,None,None,'{}','[]','[]','raw body',url,'2026-10-19T00:00:00+00:00'))
            c.commit();c.close()
            for i in range(2):call_command('import_crawler_snapshot',snapshot=str(p),stdout=StringIO())
            self.assertEqual(Company.objects.count(),1)
            self.assertEqual(PublicExperience.objects.count(),2)
            x=Company.objects.get();self.assertEqual((x.source_work_count,x.source_interview_count),(1,1))
