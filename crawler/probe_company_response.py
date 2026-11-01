"""Single-page TajrobeWiki live-response diagnostic (no queue/db writes).

Use only after confirming the site permits the requested access. Never bypass
robots.txt, HTTP access restrictions, or retry a blocked/forbidden response.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from crawl_site import inspect_saved_company_html, parse_company
from tajrobewiki_crawler import (
    BASE, CrawlHaltedError, MissingPageError, PoliteFetcher,
    TemporaryFetchError,
)

DEFAULT_URL = BASE + '/companies/' + quote('رادمان')


def validate_company_url(value: str) -> str:
    url = urlsplit(value)
    origin = urlsplit(BASE)
    if (
        url.scheme != 'https' or url.hostname != origin.hostname
        or url.port is not None or url.username or url.password
        or url.query or url.fragment
        or not url.path.startswith('/companies/')
        or url.path.rstrip('/') == '/companies'
        or '//' in url.path
    ):
        raise ValueError('Only a single clean HTTPS tajrobewiki.com/companies/... URL is supported')
    return value


def inspect_live_html(html: str, url: str, compare_html: Path | None = None) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.select_one('main')
    h1 = soup.find('h1')
    title = soup.title.get_text(' ', strip=True) if soup.title else None
    result = {
        'outcome': 'html_received',
        'received_html_bytes': len(html.encode('utf-8')),
        'html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
        'document_title': title[:200] if title else None,
        'has_h1': h1 is not None,
        'h1_text': h1.get_text(' ', strip=True)[:150] if h1 else None,
        'has_main': main is not None,
        'has_company_profile': soup.select_one('.dsk-prof') is not None,
        'has_company_sidebar': soup.select_one('.dsk-prof-aside') is not None,
    }
    try:
        parsed = parse_company(html, url)
    except (ValueError, TypeError, AttributeError) as exc:
        result['parser_ok'] = False
        result['parser_error'] = f'{type(exc).__name__}: {exc}'[:250]
    else:
        result['parser_ok'] = True
        result['parsed_name'] = parsed['name']
        result['parsed_industry'] = parsed['industry']
        result['parsed_city'] = parsed['city']
        result['parsed_size'] = parsed['employee_size']
        result['reported_experiences'] = parsed['reported_experiences']
    if compare_html is not None:
        offline = inspect_saved_company_html(compare_html, url)
        result['saved_browser_comparison'] = {
            'browser_parser_ok': offline.get('parser_ok'),
            'browser_document_title': offline.get('document_title'),
            'browser_parsed_name': offline.get('parsed_name'),
            'browser_html_bytes': offline['html_bytes'],
            'name_matches': (
                offline.get('parsed_name') == result.get('parsed_name')
                if offline.get('parser_ok') and result.get('parser_ok') else None
            ),
        }
    return result


def probe(url: str, *, permission_confirmed: bool, compare_html: Path | None,
          save_bad_html: bool, outdir: Path, fetcher_factory=PoliteFetcher) -> dict:
    if not permission_confirmed:
        raise ValueError('Explicit permission confirmation is required')
    url = validate_company_url(url)
    result: dict = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'url': url,
        'purpose': 'single_request_diagnostic',
        'crawler_retries': 0,
        'database_and_queue_unchanged': True,
        'environment_proxy_configured': any(
            bool(os.environ.get(key))
            for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')
        ),
    }
    if compare_html is not None and not compare_html.is_file():
        raise ValueError(f'Saved HTML not found: {compare_html}')
    fetch = fetcher_factory(pause=12.0, retries=0, retry_wait=30.0)
    try:
        fetch.load_robots()
    except (RuntimeError, PermissionError, OSError) as exc:
        result.update({'outcome': 'robots_check_failed', 'error': f'{type(exc).__name__}: {exc}'[:250]})
        return result
    if not fetch.rules.can_fetch(fetch.session.headers.get('User-Agent', '*'), url):
        result.update({'outcome': 'robots_disallowed', 'note': 'No company page requested'})
        return result
    try:
        html = fetch.get(url)
    except PermissionError as exc:
        result.update({'outcome': 'robots_disallowed', 'error': str(exc)[:250]})
    except CrawlHaltedError as exc:
        result.update({'outcome': 'access_or_policy_stop', 'error': str(exc)[:250],
                       'instruction': 'Do not retry; resolve site authorization/access before crawling.'})
    except MissingPageError as exc:
        result.update({'outcome': 'page_not_found', 'error': str(exc)[:250]})
    except TemporaryFetchError as exc:
        result.update({'outcome': 'temporary_connection_failure', 'error': str(exc)[:250],
                       'instruction': 'Do not start a bulk crawl based on this result.'})
    else:
        result.update(inspect_live_html(html, url, compare_html))
        if save_bad_html and not result['parser_ok']:
            # This captures one explicit user-requested snapshot for offline
            # diagnosis. Never save access/403 bodies (PoliteFetcher halts first).
            outdir.mkdir(parents=True, exist_ok=True)
            path = outdir / 'company_probe_invalid_200.html'
            path.write_text(html, encoding='utf-8')
            result['saved_invalid_html'] = str(path)
            result['privacy_warning'] = 'Review the HTML for sensitive data before sharing.'
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL, help='One TajrobeWiki company URL (default: رادمان)')
    parser.add_argument('--compare-html', type=Path, help='Previously saved company HTML, optional')
    parser.add_argument('--save-bad-html', action='store_true', help='Save a received HTML only when parsing fails')
    parser.add_argument('--diagnostics-dir', type=Path, default=Path('data/diagnostics'))
    parser.add_argument('--permission-confirmed', action='store_true', help='Confirm site access authorization')
    args = parser.parse_args()
    try:
        report = probe(args.url, permission_confirmed=args.permission_confirmed,
                       compare_html=args.compare_html, save_bad_html=args.save_bad_html,
                       outdir=args.diagnostics_dir)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report['outcome'] == 'html_received' and report.get('parser_ok') else 2


if __name__ == '__main__':
    sys.exit(main())
