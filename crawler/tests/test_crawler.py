import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tajrobewiki_crawler import listing_urls, parse_experience, prepare_db, save_review, export_jsonl

LIST_HTML = '''<html><main>
<a href="/experiences/%DA%A9%D9%86%D8%B2%D8%A7%DA%A9%D8%B3-%D8%AA%D8%AC%D8%B1%D8%A8%D9%87">نظر</a>
<a href="/experiences/%DA%A9%D9%86%D8%B2%D8%A7%DA%A9%D8%B3-%D8%AA%D8%AC%D8%B1%D8%A8%D9%87">تکرار</a>
<a href="/experiences?page=2">صفحه دوم</a><a href="https://other.example/experiences/other">خارجی</a>
</main></html>'''
DETAIL_HTML = '''<html><head><title>Test</title></head><body><nav>menu</nav><main>
<a href="/companies/%DA%A9%D9%86%D8%B2%D8%A7%DA%A9%D8%B3">کنزاکس</a>
<div>تجربه کاری ۲۵ مهر ۱۴۰۵ – اردیبهشت ۱۴۰۳ تا فروردین ۱۴۰۵</div>
<h1>ظاهر صمیمی، باطن سمی</h1>
<h2>تجربه کاری کارشناس حسابداری در کنزاکس</h2>
<p>امتیاز ۱٫۰ از ۵ (اردیبهشت ۱۴۰۳ تا فروردین ۱۴۰۵).</p>
<p>۱٫۰ – کارشناس حسابداری</p>
<div>محیط کاری برای من آرام نبود و به نظرم مدیر در جزئیات دخالت می‌کرد.</div>
<h3>نقاط قوت</h3><ul><li>بیمه تکمیلی</li></ul>
<h3>نقاط ضعف</h3><ul><li>بی نظمی کاری</li><li>مدیریت ضعیف</li></ul>
<h3>امتیاز چندمعیاره</h3><div>فرهنگ سازمانی</div><div>۱٫۰</div><div>مدیریت</div><div>۲٫۰</div>
<h3>تجربه‌های مشابه</h3><a href="/experiences/other">irrelevant</a>
</main><footer>footer</footer></body></html>'''

class TestCrawler(unittest.TestCase):
    def test_listing_unique_local_detail_links(self):
        found = listing_urls(LIST_HTML)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("https://tajrobewiki.com/experiences/"))

    def test_parse_individual_review_not_related(self):
        item = parse_experience(DETAIL_HTML, "https://tajrobewiki.com/experiences/test")
        self.assertEqual(item["company"], "کنزاکس")
        self.assertEqual(item["review_type"], "work")
        self.assertEqual(item["job_title"], "کارشناس حسابداری")
        self.assertEqual(item["published_jalali"], "۲۵ مهر ۱۴۰۵")
        self.assertEqual(item["employment_period_jalali"], "اردیبهشت ۱۴۰۳ تا فروردین ۱۴۰۵")
        self.assertEqual(item["rating_5"], 1.0)
        self.assertEqual(item["dimension_ratings_5"]["management"], 2.0)
        self.assertEqual(item["pros"], ["بیمه تکمیلی"])
        self.assertEqual(item["cons"], ["بی نظمی کاری", "مدیریت ضعیف"])
        self.assertNotIn("irrelevant", item["body"])

    def test_persistent_storage_upsert_and_export(self):
        with tempfile.TemporaryDirectory() as t:
            db = prepare_db(Path(t) / "t.sqlite")
            item = parse_experience(DETAIL_HTML, "https://tajrobewiki.com/experiences/test")
            save_review(db, item)
            save_review(db, item)
            self.assertEqual(db.execute("SELECT count(*) FROM reviews").fetchone()[0], 1)
            out = Path(t) / "out.jsonl"
            self.assertEqual(export_jsonl(db, out), 1)
            self.assertEqual(json.loads(out.read_text(encoding="utf8"))["pros"], ["بیمه تکمیلی"])
            db.close()

if __name__ == "__main__":
    unittest.main()
