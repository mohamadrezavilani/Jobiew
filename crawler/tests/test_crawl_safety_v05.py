"""Offline regression tests for v0.5: fail closed on site errors."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from crawl_site import SiteArchive, enqueue, ensure_archive_tables, diagnostic_summary, summary
from tajrobewiki_crawler import CrawlHaltedError, TemporaryFetchError, prepare_db

BASE='https://tajrobewiki.com'
BAD='<html><main><div>صفحه بدون تیتر برای نمونه</div></main></html>'

class FakeFetcher:
    def __init__(self, pages):
        self.pages=pages
        self.calls=[]
    def get(self,url):
        self.calls.append(url)
        page=self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        if page is None:
            raise AssertionError('unplanned request to '+url)
        return page

class SafetyTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp=Path(tmp.name)
        self.db=prepare_db(self.tmp/'source.db')
        self.addCleanup(self.db.close)
        ensure_archive_tables(self.db)
    def args(self,scope='companies'):
        return SimpleNamespace(scope=scope,max_items=0,max_requests=0,
            max_pages_per_section=100,pause=12,retries=0,max_consecutive_errors=2,
            max_consecutive_parse_errors=2,failures=self.tmp/'errors.jsonl')
    def test_missing_h1_stops_after_two_not_thousands(self):
        urls=[f'{BASE}/companies/test-{i}' for i in range(10)]
        for u in urls:
            enqueue(self.db,u,'company')
        self.db.commit()
        fake=FakeFetcher({u:BAD for u in urls})
        with self.assertRaisesRegex(CrawlHaltedError,'unexpected pages'):
            SiteArchive(self.db,fake,self.args()).run()
        self.assertEqual(len(fake.calls),2)
        self.assertEqual(summary(self.db).get('company_needs_review'),2)
        self.assertEqual(summary(self.db).get('company_pending'),8)
        self.assertEqual(summary(self.db).get('company_profiles'),0)
    def test_existing_company_mass_failures_prevents_all_company_fetches(self):
        for i in range(14):
            enqueue(self.db,f'{BASE}/companies/old-{i}','company')
        self.db.execute("""UPDATE site_queue SET status='failed',
            last_error='parse/storage error: page has no heading h1' WHERE kind='company'""")
        self.db.commit()
        fake=FakeFetcher({})
        with self.assertRaisesRegex(CrawlHaltedError,'Company pages disabled'):
            SiteArchive(self.db,fake,self.args()).run()
        self.assertEqual(fake.calls,[])
        self.assertEqual(diagnostic_summary(self.db)['company_missing_h1'],14)
    def test_listing_failure_does_not_move_to_company_scope(self):
        # mark no queues; site list first page fails, should never start blog/companies
        f=FakeFetcher({f'{BASE}/experiences?page=1':TemporaryFetchError('network down')})
        with self.assertRaisesRegex(CrawlHaltedError,'not moving to the next scope'):
            SiteArchive(self.db,f,self.args(scope='all')).run()
        self.assertEqual(f.calls,[f'{BASE}/experiences?page=1'])
        self.assertEqual(summary(self.db)['listing_experiences_next_page'],1)
    def test_existing_reviews_not_touched_by_diagnostics(self):
        before=self.db.execute('select count(*) from reviews').fetchone()[0]
        obj=diagnostic_summary(self.db)
        self.assertIn('issues_by_type',obj)
        self.assertEqual(self.db.execute('select count(*) from reviews').fetchone()[0],before)

if __name__=='__main__': unittest.main()
