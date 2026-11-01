"""Offline tests for parser isolation and guarded h1 fallback."""
import tempfile
import unittest
from pathlib import Path
from bs4 import BeautifulSoup
from crawl_site import clean_main, inspect_saved_company_html, parse_company

URL = 'https://tajrobewiki.com/companies/example'

class OfflineCompanyTests(unittest.TestCase):
    def test_h1_inside_main(self):
        html = '<html><main><h1>شرکت نمونه</h1><p>توضیحی درباره شرکت و استخدام در تهران</p></main></html>'
        self.assertEqual(parse_company(html,URL)['name'], 'شرکت نمونه')
    def test_h1_outside_main_but_in_document(self):
        html = '<html><body><header><h1>رادمان</h1></header><main><p>رادمان، تهران، کامپیوتر و فناوری اطلاعات</p></main></body></html>'
        self.assertEqual(parse_company(html,URL)['name'], 'رادمان')
    def test_no_h1_is_not_accepted_as_company(self):
        html = '<html><title>یک صفحه</title><main><p>رادمان تهران کامپیوتر و فناوری اطلاعات</p></main></html>'
        with self.assertRaisesRegex(ValueError, 'no heading h1'):
            parse_company(html,URL)
    def test_challenge_document_not_saved_even_with_h1(self):
        html = '<html><head><title>Access Denied</title></head><main><h1>Forbidden</h1><p>Please contact the site</p></main></html>'
        with self.assertRaisesRegex(ValueError, 'challenge'):
            parse_company(html,URL)
    def test_inspection_offline_records_nested_and_root_h1(self):
        html = '<html><head><title>کار در رادمان چطور است؟</title></head><body><header><h1>رادمان</h1></header><main><p>شرکت رادمان کامپیوتر فناوری اطلاعات تهران استخدام</p></main></body></html>'
        with tempfile.TemporaryDirectory() as d:
            f = Path(d)/'company_sample.html'
            f.write_text(html,encoding='utf-8')
            result=inspect_saved_company_html(f,URL)
        self.assertTrue(result['parser_ok'])
        self.assertTrue(result['h1_anywhere'])
        self.assertFalse(result['h1_inside_main'])
        self.assertEqual(result['parsed_name'],'رادمان')
    def test_inspection_failure_is_nonfatal(self):
        html='<html><main><p>صفحه‌ای با متن ولی بدون تیتر واقعی</p></main></html>'
        with tempfile.TemporaryDirectory() as d:
            f = Path(d)/'company_sample.html'
            f.write_text(html,encoding='utf-8')
            report=inspect_saved_company_html(f,URL)
        self.assertFalse(report['parser_ok'])
        self.assertIn('h1',report['parser_error'])

if __name__ == '__main__':
    unittest.main()
