"""Offline-only contract tests: no external network calls."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from probe_company_response import inspect_live_html, probe, validate_company_url
from tajrobewiki_crawler import CrawlHaltedError, TemporaryFetchError

HTML = '<html><head><title>شرکت رادمان</title></head><body><main><h1>رادمان</h1>' \
       '<p>درباره شرکت رادمان و معرفی خدمات و زمینه کاری شرکت در تهران</p>' \
       '</main></body></html>'
URL = 'https://tajrobewiki.com/companies/%D8%B1%D8%A7%D8%AF%D9%85%D8%A7%D9%86'


class FakeRules:
    def can_fetch(self, *_):
        return True


class FakeFetcher:
    result = HTML
    load_error = None
    def __init__(self, pause, retries, retry_wait):
        assert retries == 0
        self.session = Mock()
        self.session.headers = {'User-Agent': 'test-crawler'}
        self.rules = FakeRules()
        self.calls = 0
    def load_robots(self):
        if self.load_error:
            raise self.load_error
    def get(self, url):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class LiveProbeTests(unittest.TestCase):
    def setUp(self):
        FakeFetcher.result = HTML
        FakeFetcher.load_error = None

    def test_good_url(self):
        self.assertEqual(validate_company_url(URL), URL)

    def test_external_domain_is_refused(self):
        with self.assertRaises(ValueError):
            validate_company_url('https://other.example/companies/a')

    def test_other_paths_refused(self):
        with self.assertRaises(ValueError):
            validate_company_url('https://tajrobewiki.com/experiences/a')

    def test_query_refused(self):
        with self.assertRaises(ValueError):
            validate_company_url(URL + '?token=private')

    def test_permission_required_before_network(self):
        with self.assertRaises(ValueError):
            probe(URL, permission_confirmed=False, compare_html=None,
                  save_bad_html=False, outdir=Path('x'), fetcher_factory=FakeFetcher)

    def test_successful_parse(self):
        out = probe(URL, permission_confirmed=True, compare_html=None,
                    save_bad_html=False, outdir=Path('x'), fetcher_factory=FakeFetcher)
        self.assertEqual(out['outcome'], 'html_received')
        self.assertTrue(out['parser_ok'])
        self.assertEqual(out['parsed_name'], 'رادمان')

    def test_access_denial_stops(self):
        FakeFetcher.result = CrawlHaltedError('stopping on HTTP 403')
        out = probe(URL, permission_confirmed=True, compare_html=None,
                    save_bad_html=False, outdir=Path('x'), fetcher_factory=FakeFetcher)
        self.assertEqual(out['outcome'], 'access_or_policy_stop')

    def test_connection_error_not_retried(self):
        FakeFetcher.result = TemporaryFetchError('connection reset')
        out = probe(URL, permission_confirmed=True, compare_html=None,
                    save_bad_html=False, outdir=Path('x'), fetcher_factory=FakeFetcher)
        self.assertEqual(out['outcome'], 'temporary_connection_failure')

    def test_empty_html_error(self):
        out = inspect_live_html('<html><title>oops</title></html>', URL)
        self.assertFalse(out['parser_ok'])

    def test_save_failure_html_only_when_enabled(self):
        FakeFetcher.result = '<html><body>No h1</body></html>'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            out = probe(URL, permission_confirmed=True, compare_html=None,
                        save_bad_html=True, outdir=p, fetcher_factory=FakeFetcher)
            self.assertFalse(out['parser_ok'])
            self.assertTrue((p / 'company_probe_invalid_200.html').is_file())

    def test_no_save_denial(self):
        FakeFetcher.result = CrawlHaltedError('stopping on HTTP 403')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            probe(URL, permission_confirmed=True, compare_html=None,
                  save_bad_html=True, outdir=p, fetcher_factory=FakeFetcher)
            self.assertEqual(list(p.iterdir()), [])

    def test_compare_existing_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'browser.html'
            p.write_text(HTML, encoding='utf-8')
            out = inspect_live_html(HTML, URL, compare_html=p)
            self.assertTrue(out['saved_browser_comparison']['name_matches'])


if __name__ == '__main__':
    unittest.main()
