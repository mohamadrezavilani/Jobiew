import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from crawl_site import (
    SiteArchive, detail_links, page_count, parse_company, parse_blog,
    ensure_archive_tables, summary, enqueue, export_table,
)
from tajrobewiki_crawler import prepare_db

LIST = '''<html><main><h1>تجربه‌ها</h1><div>۲ تجربه · صفحه ۱ از ۱</div>
<a href="/experiences/one">First</a><a href="/experiences/two">Second</a>
<a href="/experiences?page=2">Next</a><a href="https://outside.com/experiences/m">Out</a></main></html>'''
REVIEW = '''<html><body><main><a href="/companies/example">شرکت نمونه</a>
<div>تجربه کاری ۲۵ مهر ۱۴۰۵</div><h1>تجربه محیط کار</h1>
<h2>تجربه کاری برنامه نویس در شرکت نمونه</h2>
<p>امتیاز ۳٫۵ از ۵</p>
<div>محیط کاری مناسب است اما گاهی ساعات کاری خیلی زیاد می‌شود.</div>
<h3>نقاط قوت</h3><p>تیم فنی</p><h3>نقاط ضعف</h3><p>ساعات کاری</p>
<h3>امتیاز چندمعیاره</h3><p>مدیریت</p><div>۳٫۰</div>
<h3>تجربه‌های مشابه</h3></main></body></html>'''
COMPANY = '''<html><main><h1>شرکت نمونه</h1><p>تهران · ۴۵ تجربه · بیش از ۱۰۰ نفر</p>
<a href="https://example.org">example.org</a>
<h2>امتیاز چندمعیاره</h2><div>مدیریت</div><div>۳٫۰</div>
<h2>خلاصه تجربه‌ها (هوش مصنوعی)</h2><p>این خلاصه منتشرشده توسط منبع است، نه شواهد مستقل.</p>
</main></html>'''
BLOG = '''<html><main><h1>راهنمای شغلی</h1><p>راهنمای جامع توسعه شغلی و مهارت‌های مصاحبه.</p>
<h2>نکات</h2><p>پیش از مصاحبه سوالات خود را آماده کنید.</p></main></html>'''

class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
    def get(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError('unexpected request: ' + url)
        return self.pages[url]

class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = prepare_db(Path(self.tmp.name)/'reviews.db')
        self.addCleanup(self.db.close)
        ensure_archive_tables(self.db)
    def args(self, scope='experiences', items=100, req=100):
        return SimpleNamespace(scope=scope,max_items=items,max_requests=req,
                               max_pages_per_section=100,pause=12,retries=0,
                               max_consecutive_errors=2, max_consecutive_parse_errors=2,failures=Path(self.tmp.name)/'errors.jsonl')
    def test_detail_urls_only_and_unique(self):
        self.assertEqual(detail_links(LIST, 'experience'),
                         ['https://tajrobewiki.com/experiences/one','https://tajrobewiki.com/experiences/two'])
    def test_pagination_count(self):
        self.assertEqual(page_count(LIST, 'experiences', 1), 2)
        self.assertEqual(page_count('<main><p>صفحه ۱ از ۳۷۳</p></main>', 'experiences',1),373)
        self.assertEqual(page_count(BLOG, 'blog', 1), 1)
    def test_parse_company_metadata(self):
        item = parse_company(COMPANY, 'https://tajrobewiki.com/companies/example')
        self.assertEqual(item['name'], 'شرکت نمونه')
        self.assertEqual(item['reported_experiences'], 45)
        self.assertEqual(item['website'], 'https://example.org')
        self.assertEqual(item['dimension_ratings_5'].get('management'), 3.0)
    def test_blog(self):
        item = parse_blog(BLOG, 'https://tajrobewiki.com/blog/sample')
        self.assertIn('مصاحبه', item['text'])
    def test_checkpoint_resume_and_existing_records(self):
        # Existing v0.2 record must be skipped when discovered by v0.4.
        from tajrobewiki_crawler import parse_experience, save_review
        one = 'https://tajrobewiki.com/experiences/one'
        save_review(self.db, parse_experience(REVIEW, one))
        pages={'https://tajrobewiki.com/experiences?page=1': LIST,
               'https://tajrobewiki.com/experiences/two': REVIEW}
        fetcher=FakeFetcher(pages)
        site=SiteArchive(self.db,fetcher,self.args(items=1))
        site.run()
        self.assertEqual(summary(self.db)['reviews'],2)
        self.assertNotIn(one,fetcher.calls)
        self.assertFalse(summary(self.db)['listing_experiences_complete'])
        # A second run finishes without repeating fetched reviews.
        fetcher2=FakeFetcher({'https://tajrobewiki.com/experiences?page=2': LIST})
        site2=SiteArchive(self.db,fetcher2,self.args(items=10))
        site2.run()
        self.assertEqual(summary(self.db)['reviews'],2)
    def test_company_and_blog_exports(self):
        from crawl_site import save_profile, save_article
        save_profile(self.db,parse_company(COMPANY,'https://tajrobewiki.com/companies/example'))
        save_article(self.db,parse_blog(BLOG,'https://tajrobewiki.com/blog/sample'))
        cf=Path(self.tmp.name)/'company.jsonl'
        bf=Path(self.tmp.name)/'blog.jsonl'
        self.assertEqual(export_table(self.db,'company_profiles',cf),1)
        self.assertEqual(export_table(self.db,'blog_articles',bf),1)
        self.assertEqual(json.loads(cf.read_text(encoding='utf-8'))['name'],'شرکت نمونه')
    def test_queue_idempotent(self):
        enqueue(self.db,'https://tajrobewiki.com/blog/something','blog')
        enqueue(self.db,'https://tajrobewiki.com/blog/something','blog')
        self.db.commit()
        self.assertEqual(summary(self.db)['blog_pending'],1)
    def test_unexpected_empty_page_does_not_claim_complete(self):
        html='<html><main><a href="/experiences/test">Review</a></main></html>'
        pages={'https://tajrobewiki.com/experiences?page=1':html,
               'https://tajrobewiki.com/experiences/test':REVIEW,
               'https://tajrobewiki.com/experiences?page=2':'<html><main>Empty</main></html>'}
        from tajrobewiki_crawler import CrawlHaltedError
        with self.assertRaises(CrawlHaltedError):
            SiteArchive(self.db,FakeFetcher(pages),self.args(items=50)).run()
        self.assertFalse(summary(self.db)['listing_experiences_complete'])

if __name__=='__main__': unittest.main()
