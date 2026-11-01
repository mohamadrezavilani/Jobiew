import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.robotparser import RobotFileParser
from unittest.mock import Mock, patch
import requests

import tajrobewiki_crawler as crawler
from test_crawler import DETAIL_HTML


class FakeResponse:
    def __init__(self, status=200, text='<html>ok</html>'):
        self.status_code = status
        self.text = text
        self.headers = {'Content-Type': 'text/html'}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}')


class FetchResilienceTests(unittest.TestCase):
    def fetcher(self, retries=1):
        f = crawler.PoliteFetcher(8, retries=retries, retry_wait=10)
        f.rules.parse(['User-agent: *', 'Allow: /'])
        f.rules_ready = True
        return f

    def test_disconnection_then_success(self):
        f = self.fetcher()
        f.session.get = Mock(side_effect=[requests.ConnectionError('RemoteDisconnected'), FakeResponse()])
        with patch.object(f, '_throttle'), patch.object(crawler.time, 'sleep') as sleeper:
            self.assertIn('ok', f.get('https://tajrobewiki.com/experiences/test'))
        self.assertEqual(f.session.get.call_count, 2)
        sleeper.assert_called_once_with(10)

    def test_repeated_disconnection_skips_with_temporary_error(self):
        f = self.fetcher()
        f.session.get = Mock(side_effect=requests.ConnectionError('RemoteDisconnected'))
        with patch.object(f, '_throttle'), patch.object(crawler.time, 'sleep'):
            with self.assertRaises(crawler.TemporaryFetchError):
                f.get('https://tajrobewiki.com/experiences/test')
        self.assertEqual(f.session.get.call_count, 2)

    def test_429_stops_without_retry(self):
        f = self.fetcher()
        f.session.get = Mock(return_value=FakeResponse(429))
        with patch.object(f, '_throttle'), patch.object(crawler.time, 'sleep') as sleeper:
            with self.assertRaisesRegex(RuntimeError, '429'):
                f.get('https://tajrobewiki.com/experiences/test')
        self.assertEqual(f.session.get.call_count, 1)
        sleeper.assert_not_called()

    def test_503_is_retried_once(self):
        f = self.fetcher()
        f.session.get = Mock(side_effect=[FakeResponse(503), FakeResponse()])
        with patch.object(f, '_throttle'), patch.object(crawler.time, 'sleep'):
            self.assertIn('ok', f.get('https://tajrobewiki.com/experiences/test'))
        self.assertEqual(f.session.get.call_count, 2)

    def test_robots_denial_prevents_requests(self):
        f = self.fetcher()
        f.rules = RobotFileParser()
        f.rules.parse(['User-agent: *', 'Disallow: /experiences'])
        f.session.get = Mock()
        with self.assertRaises(PermissionError):
            f.get('https://tajrobewiki.com/experiences/test')
        f.session.get.assert_not_called()

    def test_main_skips_one_failure_exports_two_and_resumes_later(self):
        a = '/experiences/example-a'
        b = '/experiences/example-b'
        c = '/experiences/example-c'
        listing = '<html><main>' + ''.join(f'<a href="{x}">review</a>' for x in [a, b, c]) + '</main></html>'

        class FakeFetcher:
            allow_b = False
            calls = []

            def __init__(self, *args, **kwargs):
                pass

            def load_robots(self):
                pass

            def get(self, url):
                FakeFetcher.calls.append(url)
                if '?type=' in url:
                    return listing
                if url.endswith('example-b') and not FakeFetcher.allow_b:
                    raise crawler.TemporaryFetchError('failed: sample disconnect')
                return DETAIL_HTML

        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            args = [
                'tajrobewiki_crawler.py', '--permission-confirmed', '--max-pages', '1',
                '--max-reviews', '20', '--db', str(t/'reviews.db'),
                '--jsonl', str(t/'reviews.jsonl'), '--failures', str(t/'failed_requests.jsonl')
            ]
            with patch.object(crawler, 'PoliteFetcher', FakeFetcher), patch('sys.argv', args):
                crawler.main()
            conn = sqlite3.connect(t/'reviews.db')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 2)
            self.assertEqual(len((t/'reviews.jsonl').read_text(encoding='utf-8').splitlines()), 2)
            failures = [json.loads(x) for x in (t/'failed_requests.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(failures[0]['stage'], 'review')
            self.assertTrue(failures[0]['url'].endswith('example-b'))

            FakeFetcher.allow_b = True
            FakeFetcher.calls.clear()
            with patch.object(crawler, 'PoliteFetcher', FakeFetcher), patch('sys.argv', args):
                crawler.main()
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 3)
            detail_calls = [x for x in FakeFetcher.calls if '/experiences/' in x]
            self.assertEqual(len(detail_calls), 1)
            self.assertTrue(detail_calls[0].endswith('example-b'))
            conn.close()


if __name__ == '__main__':
    unittest.main()
