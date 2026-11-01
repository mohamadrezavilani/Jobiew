"""Version 0.7: schema compatibility and metadata extraction with no HTTP."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from crawl_site import parse_company, ensure_archive_tables, save_profile, export_table
from tajrobewiki_crawler import prepare_db

URL = 'https://tajrobewiki.com/companies/example'
HTML = '''<html><head><title>کار در شرکت نمونه | ویکی‌تجربه</title></head>
<body><main><div class="dsk-prof"><aside class="dsk-prof-aside">
<div class="card card-pad"><h1>شرکت نمونه</h1>
<a href="/companies?industry=IT">فناوری اطلاعات</a>
<a href="/companies?city=%D8%AA%D9%87%D8%B1%D8%A7%D9%86">تهران</a>
<span>۲ - ۱۰ نفر</span><span class="badge-verify">احراز هویت‌شده</span></div>
</aside><div><div class="card card-pad">توضیح اولیه شرکت نمونه</div>
<h2>استخدام در شرکت نمونه</h2><p>از مجموع <span>۱</span> تجربه ثبت‌شده
<span>۰</span> مورد تجربه کاری و <span>۱</span> مورد تجربه مصاحبه استخدام است.</p>
<h3>تجربه کاری چگونه است؟</h3><p>داده کافی وجود ندارد</p>
<ul><li>آخرین به‌روزرسانی: <time>۱۴۰۵/۷/۲۶</time></li></ul></div></div>
<section aria-label="تجربه‌های مرتبط"><h2>تجربه‌های مرتبط</h2><p>اتهام نامرتبط در شرکت دیگری</p></section>
</main>
<script type="application/ld+json">{"@type":"Organization","description":"توضیح معتبر معرفی شرکت", "alternateName":"examplecorp", "address":{"addressLocality":"تهران"}}</script>
</body></html>'''

class CompanyMetadataV07(unittest.TestCase):
    def test_complete_fields_and_no_related_company_contamination(self):
        x = parse_company(HTML, URL)
        self.assertEqual(x['name'], 'شرکت نمونه')
        self.assertEqual(x['industry'], 'فناوری اطلاعات')
        self.assertEqual(x['city'], 'تهران')
        self.assertEqual(x['employee_size'], '۲ - ۱۰ نفر')
        self.assertEqual(x['reported_experiences'], 1)
        self.assertEqual(x['work_experiences'], 0)
        self.assertEqual(x['interview_experiences'], 1)
        self.assertEqual(x['source_last_updated'], '۱۴۰۵/۷/۲۶')
        self.assertTrue(x['verified_on_source'])
        self.assertEqual(x['alternate_name'], 'examplecorp')
        self.assertEqual(x['description'], 'توضیح معتبر معرفی شرکت')
        self.assertNotIn('اتهام نامرتبط', x['text'])
        self.assertEqual(x['dimension_ratings_5'], {})
    def test_existing_database_auto_migration_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            dbpath=Path(d)/'old.db'
            db=prepare_db(dbpath)
            db.execute('''CREATE TABLE company_profiles (
                url TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT,
                employee_size TEXT, reported_experiences INTEGER,
                dimension_ratings_json TEXT NOT NULL, sections_json TEXT NOT NULL,
                text TEXT NOT NULL, crawled_at_utc TEXT NOT NULL)''')
            db.execute("INSERT INTO company_profiles VALUES (?,?,?,?,?,?,?,?,?)",
                       ('https://example.org/existing','قدیمی',None,None,None,'{}','{}','متن قبلی','2026-10-17T00:00:00'))
            db.commit()
            ensure_archive_tables(db)
            ensure_archive_tables(db)
            self.assertEqual(db.execute('SELECT name FROM company_profiles WHERE url=?',
                                        ('https://example.org/existing',)).fetchone()[0], 'قدیمی')
            save_profile(db,parse_company(HTML,URL))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM company_profiles').fetchone()[0],2)
            out=Path(d)/'companies.jsonl'
            self.assertEqual(export_table(db,'company_profiles',out),2)
            objs=[json.loads(x) for x in out.read_text('utf8').splitlines()]
            new=next(x for x in objs if x['url']==URL)
            self.assertTrue(new['verified_on_source'])
            self.assertEqual(new['work_experiences'],0)
            db.close()
    def test_no_fake_source_website_from_schema_org_url(self):
        html=HTML.replace('</body>', '<script type="application/ld+json">{"@type":"Organization","url":"https://tajrobewiki.com/companies/example"}</script></body>')
        self.assertIsNone(parse_company(html, URL)['website'])

if __name__=='__main__':
    unittest.main()
