"""Checkpointed, robots-aware TajrobeWiki public-page archive.

Requires authorization to collect and reuse third-party content. Does not
bypass login, access controls, HTTP 403/429, or robots exclusions.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup

from tajrobewiki_crawler import (
    BASE, CrawlHaltedError, MissingPageError, PoliteFetcher,
    TemporaryFetchError, DIMENSIONS, _section, norm, rating, western,
    listing_urls, parse_experience, prepare_db, save_review, export_jsonl,
    record_failure, same_site_url,
)

SCOPES = {"experiences": "experience", "companies": "company", "blog": "blog"}
FARSI_NUM = re.compile(r"\b\d+(?:[,.]\d+)?\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def detail_links(html: str, kind: str) -> list[str]:
    """Only article/detail links; omit /companies?filters and page controls."""
    prefix = {"experience": "/experiences/", "company": "/companies/", "blog": "/blog/"}[kind]
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup.body or soup
    urls = []
    seen = set()
    for a in main.select("a[href]"):
        url = same_site_url(a["href"], prefix)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def page_count(html: str, section: str, current_page: int) -> int | None:
    """Get an advertised last page, not an estimate from the first page size."""
    soup = BeautifulSoup(html, "html.parser")
    n = 0
    for a in soup.find_all("a", href=True):
        u = urlsplit(a["href"])
        if u.path.rstrip("/") not in ("", "/" + section):
            continue
        values = parse_qs(u.query).get("page", [])
        if values and values[0].isdigit():
            n = max(n, int(values[0]))
    if section == "experiences":
        text = western(soup.get_text(" ", strip=True))
        m = re.search(r"صفحه\s*\d+\s*از\s*(\d+)", text)
        if m:
            n = max(n, int(m.group(1)))
    if n:
        return n
    return 1 if section == "blog" and current_page == 1 else None


def clean_main(html: str):
    """Extract the primary page text, supporting h1 in or outside <main>.

    Some layouts place the visible h1 in a sibling of <main>. The former
    implementation only searched descendants of <main>, reporting missing h1
    even when the document clearly contained one. Do not infer that pages
    without a real h1, or responses that look like access challenges, are
    valid company profiles.
    """
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("title")
    document_title = norm(title_node.get_text(" ", strip=True)) if title_node else ""
    # Catch only obvious error/challenge titles. This does not replace HTTP
    # status checks by PoliteFetcher, which still stops on 403/429.
    challenge_markers = (
        "access denied", "just a moment", "checking your browser",
        "too many requests", "forbidden", "verify you are human",
        "attention required!", "دسترسی غیرمجاز", "دسترسی شما محدود",
    )
    if any(marker in document_title.casefold() for marker in challenge_markers):
        raise ValueError("access/challenge document, not a content page")
    main = soup.select_one("main") or soup.select_one("article") or soup.body
    if main is None:
        raise ValueError("page has no main content")
    # Prefer an h1 inside main; fall back to one in the document when the
    # layout places the page heading outside main. Never synthesize an h1
    # from the URL or title: an access/placeholder page must not be stored.
    h1 = main.find("h1") or soup.find("h1")
    if h1 is None:
        raise ValueError("page has no heading h1 (in main or document)")
    name = norm(h1.get_text(" ", strip=True))
    if not name:
        raise ValueError("page heading h1 is empty")
    for e in main.select("script, style, noscript, svg, nav, footer, form, button, aside"):
        e.decompose()
    return main, name


def inspect_saved_company_html(path: Path, url: str) -> dict:
    """Dry offline analysis, never fetches or writes to the database."""
    html = path.read_text(encoding="utf-8-sig", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main")
    h1 = soup.find("h1")
    main_h1 = main.find("h1") if main else None
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    report = {
        "file": path.name,
        "html_bytes": path.stat().st_size,
        "document_title": norm(page_title),
        "has_main": main is not None,
        "h1_anywhere": h1 is not None,
        "h1_inside_main": main_h1 is not None,
        "document_h1_text": norm(h1.get_text(" ", strip=True)) if h1 else None,
        "main_text_characters": len(norm(main.get_text(" ", strip=True))) if main else 0,
        "source": "offline saved HTML, not a live crawler response",
    }
    try:
        item = parse_company(html, url)
    except ValueError as exc:
        report.update({"parser_ok": False, "parser_error": str(exc)})
    else:
        report.update({
            "parser_ok": True,
            "parsed_name": item["name"],
            "parsed_size": item["employee_size"],
            "parsed_industry": item["industry"],
            "parsed_city": item["city"],
            "parsed_description": item["description"],
            "reported_experiences": item["reported_experiences"],
            "work_experiences": item["work_experiences"],
            "interview_experiences": item["interview_experiences"],
            "verified_on_source": item["verified_on_source"],
            "alternate_name": item["alternate_name"],
            "source_last_updated": item["source_last_updated"],
            "dimension_keys": sorted(item["dimension_ratings_5"]),
            "section_headings": list(item["sections"])[:12],
        })
    report["note"] = (
        "This checks only the saved browser HTML. An earlier HTTP 403 or "
        "a different crawler response still requires separate access diagnosis. "
        "No HTTP requests or DB writes were performed."
    )
    return report


def headed_sections(main) -> dict[str, str]:
    """Separate content blocks for transparency; no LLM-generated score inferred."""
    sections: dict[str, str] = {}
    for heading in main.find_all(["h2", "h3"]):
        title = norm(heading.get_text(" ", strip=True))
        chunks = []
        for sib in heading.next_siblings:
            if getattr(sib, "name", None) in {"h2", "h3"}:
                break
            if hasattr(sib, "get_text"):
                t = norm(sib.get_text(" ", strip=True))
            else:
                t = norm(str(sib))
            if t:
                chunks.append(t)
        if title:
            sections[title] = "\n".join(chunks)[:25000]
    return sections


def _organization_ld(soup) -> dict:
    """Extract site-provided schema.org Organization metadata; never treat
    Organization.url (the TajrobeWiki profile) as the company's official site.
    """
    def candidates(value):
        if isinstance(value, list):
            for x in value:
                yield from candidates(x)
        elif isinstance(value, dict):
            yield value
            if isinstance(value.get("@graph"), list):
                yield from candidates(value["@graph"])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for obj in candidates(data):
            if obj.get("@type") in ("Organization", "Corporation"):
                return obj
    return {}


def _company_field_from_filter(container, field: str) -> str | None:
    # The public site exposes its canonical labels in query links, rather
    # than by attaching stable data attributes to the corresponding text.
    for a in container.select('a[href]'):
        values = parse_qs(urlsplit(a.get('href', '')).query).get(field)
        if values:
            label = norm(a.get_text(' ', strip=True))
            return label or norm(values[0])
    return None


def _company_counts(content) -> tuple[int | None, int | None, int | None]:
    # Prioritize labelled values in the company overview, not the sidebar
    # '0 تجربه' score card or the related-companies recommendation area.
    overview = None
    for p in content.find_all('p'):
        txt = norm(p.get_text(' ', strip=True))
        if 'از مجموع' in txt and 'تجربه کاری' in txt and 'مصاحبه' in txt:
            overview = western(txt)
            break
    if not overview:
        return None, None, None
    total_m = re.search(r'از مجموع\s*(\d+)\s*تجربه', overview)
    work_m = re.search(r'(\d+)\s*مورد تجربه کاری', overview)
    interview_m = re.search(r'(\d+)\s*مورد تجربه مصاحبه', overview)
    return tuple(int(m.group(1)) if m else None for m in (total_m, work_m, interview_m))


def _company_faq(content) -> dict[str, str]:
    questions = {}
    for h in content.find_all('h3'):
        question = norm(h.get_text(' ', strip=True))
        if not question.endswith('؟'):
            continue
        paragraph = h.find_next_sibling('p')
        if paragraph and paragraph.parent is h.parent:
            answer = norm(paragraph.get_text(' ', strip=True))
            if answer:
                questions[question] = answer[:3000]
    return questions


def parse_company(html: str, url: str) -> dict:
    # clean_main validates obvious access/challenge pages. It intentionally
    # strips <aside>; metadata on TajrobeWiki company pages resides INSIDE
    # an <aside>, hence we parse an untouched document for company metadata.
    main_clean, name = clean_main(html)
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.select_one('main') or soup.select_one('article') or soup.body
    if main is None:
        raise ValueError('company main not found')
    org = _organization_ld(soup)
    # Company-specific blocks only. Do NOT include recommendations about other
    # companies or related experiences in the target company's text.
    profile = main.select_one('.dsk-prof')
    sidebar = main.select_one('.dsk-prof-aside')
    content = (profile.find('div', recursive=False) if profile else main_clean)
    if content is None:
        content = main_clean
    metadata = sidebar or main
    industry = _company_field_from_filter(metadata, 'industry')
    city = _company_field_from_filter(metadata, 'city')
    addr = org.get('address') if isinstance(org.get('address'), dict) else {}
    industry = industry or (norm(org['knowsAbout']) if isinstance(org.get('knowsAbout'), str) else None)
    city = city or (norm(addr['addressLocality']) if isinstance(addr.get('addressLocality'), str) else None)
    size = None
    # Text may be '۲ - ۱۰ نفر'. Only match a standalone metadata span,
    # avoiding unrelated references in embedded reviews or FAQ.
    for span in metadata.select('span'):
        txt = norm(span.get_text(' ', strip=True))
        if re.fullmatch(r'[0-9۰-۹٠-٩\s–—-]+\s*نفر', txt):
            size = txt
            break
    if not size and sidebar is None:
        size = next((norm(x) for x in main.stripped_strings
                     if re.fullmatch(r'[0-9۰-۹٠-٩\s–—-]+\s*نفر', norm(x))), None)
    verified = bool(sidebar and sidebar.select_one('.badge-verify')) if sidebar else None
    description = org.get('description') if isinstance(org.get('description'), str) else None
    if description:
        description = norm(description)
    elif profile:
        intro = content.select_one('div.card.card-pad')
        if intro:
            description = norm(intro.get_text(' ', strip=True)) or None
    website = None
    # Check company profile first. A related company's hyperlink is NOT its
    # official website. If the page has no specific profile container (unit
    # test / other layout), use the non-site links from main as fallback.
    linkscope = sidebar or main
    for a in linkscope.find_all('a', href=True):
        u = urlsplit(a['href'])
        if u.scheme in {'http', 'https'} and u.hostname and u.hostname not in {'tajrobewiki.com', 'www.tajrobewiki.com'}:
            website = a['href']
            break
    total, work, interview = _company_counts(content)
    # Simple HTML variants retained for backwards compatibility, but never
    # claim a count if no safely identifiable value is present.
    if total is None and profile is None:
        header = western(norm(main_clean.get_text(' ', strip=True))[:400])
        mm = re.search(r'(\d+)\s*تجربه', header)
        if mm:
            total = int(mm.group(1))
    dimensions = {}
    ratings_scope = sidebar or main_clean
    lines = [norm(v) for v in ratings_scope.stripped_strings if norm(v)]
    for i, key in enumerate(lines[:-1]):
        if key in DIMENSIONS:
            score = rating(lines[i + 1])
            if score is not None:
                dimensions[DIMENSIONS[key]] = score
    # Collect profile-specific narrative / informational content only. FAQ
    # and editorial summary are SITE CONTENT, not independent employee votes.
    faq = _company_faq(content)
    sections = {}
    if description:
        sections['معرفی شرکت'] = description
    if total is not None:
        sections['آمار تجربه‌ها'] = f'مجموع: {total}; کاری: {work}; مصاحبه: {interview}'
    sections.update(faq)
    update_date = None
    for li in content.select('li'):
        t = norm(li.get_text(' ', strip=True))
        if 'آخرین به‌روزرسانی:' in t:
            match = re.search(r'[0-9۰-۹٠-٩]{4}/[0-9۰-۹٠-٩]{1,2}/[0-9۰-۹٠-٩]{1,2}', t)
            if match:
                update_date = match.group(0)
                break
    # Build a small attributable summary and avoid snippets about unrelated
    # companies. No invented score, and no claims of independently verified employment.
    text_parts = [f'شرکت: {name}']
    for label, val in (('حوزه فعالیت',industry),('شهر',city),('تعداد کارکنان',size),('توضیحات شرکت',description)):
        if val:
            text_parts.append(f'{label}: {val}')
    if total is not None:
        text_parts.append(f'تجربه‌های ثبت‌شده: {total}; تجربه کاری: {work}; مصاحبه: {interview}')
    for q, answer in faq.items():
        text_parts.append(q + ' ' + answer)
    text = '\n'.join(text_parts)
    if len(text) < 25 and profile is None:
        # Legacy/simple layouts have no separate metadata aside. Keep their
        # main article text rather than reject an otherwise valid page.
        text = norm(main_clean.get_text(' ', strip=True))[:200000]
    if len(text) < 25:
        raise ValueError('company page lacks usable profile content')
    logo = org.get('logo') if isinstance(org.get('logo'), str) else None
    alternate_name = org.get('alternateName') if isinstance(org.get('alternateName'), str) else None
    return {
        'url': url, 'name': name, 'website': website, 'employee_size': size,
        'reported_experiences': total, 'dimension_ratings_5': dimensions,
        'sections': sections, 'text': text[:200000], 'crawled_at_utc': utc_now(),
        'industry': industry, 'city': city, 'description': description,
        'work_experiences': work, 'interview_experiences': interview,
        'verified_on_source': verified, 'logo_url': logo,
        'alternate_name': norm(alternate_name) if alternate_name else None,
        'source_last_updated': update_date,
    }


def parse_blog(html: str, url: str) -> dict:
    main, title = clean_main(html)
    text = norm(main.get_text("\n", strip=True))
    if len(text) < 50:
        raise ValueError("blog article missing substantive text")
    return {"url": url, "title": title, "text": text[:400000],
            "sections": headed_sections(main), "crawled_at_utc": utc_now()}


def ensure_archive_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS site_queue (
        url TEXT PRIMARY KEY, kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT, first_seen_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS site_queue_kind_status ON site_queue(kind, status);
    CREATE TABLE IF NOT EXISTS site_listings (
        section TEXT PRIMARY KEY, next_page INTEGER NOT NULL DEFAULT 1,
        last_page INTEGER, completed INTEGER NOT NULL DEFAULT 0,
        updated_utc TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS company_profiles (
        url TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT, employee_size TEXT,
        reported_experiences INTEGER, dimension_ratings_json TEXT NOT NULL,
        sections_json TEXT NOT NULL, text TEXT NOT NULL, crawled_at_utc TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS blog_articles (
        url TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL,
        sections_json TEXT NOT NULL, crawled_at_utc TEXT NOT NULL
    );
    """)
    # Additive upgrade; existing company rows, reviews, and pending/failed
    # queues are preserved, and this migration is safe to run repeatedly.
    extra_columns = {
        "industry": "TEXT", "city": "TEXT", "description": "TEXT",
        "work_experiences": "INTEGER", "interview_experiences": "INTEGER",
        "verified_on_source": "INTEGER", "logo_url": "TEXT",
        "alternate_name": "TEXT", "source_last_updated": "TEXT",
    }
    existing = {row[1] for row in db.execute("PRAGMA table_info(company_profiles)")}
    for col, data_type in extra_columns.items():
        if col not in existing:
            db.execute(f"ALTER TABLE company_profiles ADD COLUMN {col} {data_type}")
    db.commit()


def enqueue(db: sqlite3.Connection, url: str, kind: str) -> None:
    existing = {"experience": "reviews", "company": "company_profiles", "blog": "blog_articles"}[kind]
    already = db.execute(f"SELECT 1 FROM {existing} WHERE url=?", (url,)).fetchone()
    status = "done" if already else "pending"
    now = utc_now()
    db.execute("""INSERT OR IGNORE INTO site_queue
        (url, kind, status, first_seen_utc, updated_utc) VALUES (?,?,?,?,?)""",
        (url, kind, status, now, now))


def set_status(db, url: str, status: str, error: str | None = None) -> None:
    db.execute("""UPDATE site_queue SET status=?, attempts=attempts+1,
        last_error=?, updated_utc=? WHERE url=?""", (status, error, utc_now(), url))
    db.commit()


def next_queue(db, kind: str):
    return db.execute("""SELECT url FROM site_queue WHERE kind=? AND status='pending'
                        ORDER BY first_seen_utc, rowid LIMIT 1""", (kind,)).fetchone()


def save_profile(db, item: dict) -> None:
    cols = [
        'url', 'name', 'website', 'employee_size', 'reported_experiences',
        'dimension_ratings_json', 'sections_json', 'text', 'crawled_at_utc',
        'industry', 'city', 'description', 'work_experiences',
        'interview_experiences', 'verified_on_source', 'logo_url',
        'alternate_name', 'source_last_updated',
    ]
    values = [
        item['url'], item['name'], item.get('website'), item.get('employee_size'),
        item.get('reported_experiences'),
        json.dumps(item.get('dimension_ratings_5', {}), ensure_ascii=False),
        json.dumps(item.get('sections', {}), ensure_ascii=False),
        item['text'], item['crawled_at_utc'], item.get('industry'),
        item.get('city'), item.get('description'), item.get('work_experiences'),
        item.get('interview_experiences'),
        None if item.get('verified_on_source') is None else int(item['verified_on_source']),
        item.get('logo_url'), item.get('alternate_name'), item.get('source_last_updated'),
    ]
    updates = ', '.join(f'{col}=excluded.{col}' for col in cols if col != 'url')
    placeholders = ','.join('?' for _ in cols)
    db.execute(f"INSERT INTO company_profiles ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT(url) DO UPDATE SET {updates}", values)
    db.commit()


def save_article(db, item: dict) -> None:
    db.execute("""INSERT INTO blog_articles VALUES (?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET title=excluded.title, text=excluded.text,
        sections_json=excluded.sections_json, crawled_at_utc=excluded.crawled_at_utc""",
        (item["url"], item["title"], item["text"],
         json.dumps(item["sections"], ensure_ascii=False), item["crawled_at_utc"]))
    db.commit()


def export_table(db, table: str, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    db.row_factory = sqlite3.Row
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in db.execute(f"SELECT * FROM {table} ORDER BY url"):
            obj = dict(row)
            if table == 'company_profiles' and obj.get('verified_on_source') is not None:
                obj['verified_on_source'] = bool(obj['verified_on_source'])
            for key, target in (("sections_json", "sections"), ("dimension_ratings_json", "dimension_ratings_5")):
                if key in obj:
                    obj[target] = json.loads(obj.pop(key))
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            count += 1
    return count


class RequestBudgetExhausted(Exception):
    pass


class SiteArchive:
    def __init__(self, db: sqlite3.Connection, fetcher: PoliteFetcher, args):
        self.db, self.fetch, self.args = db, fetcher, args
        self.requests, self.added, self.errors, self.consecutive_errors = 0, 0, 0, 0
        self.enabled = ["experiences", "blog", "companies"] if args.scope == "all" else [args.scope]
        self.parse_errors_in_row = 0

    def quota(self):
        return ((self.args.max_items and self.added >= self.args.max_items) or
                (self.args.max_requests and self.requests >= self.args.max_requests))

    def get(self, url):
        if self.args.max_requests and self.requests >= self.args.max_requests:
            raise RequestBudgetExhausted()
        # Attempts inside the shared fetcher can add retries; --max-requests
        # limits logical fetch calls, not wire-level attempts.
        self.requests += 1
        return self.fetch.get(url)

    def process_queue(self, section: str, max_attempts: int | None = None) -> None:
        kind = SCOPES[section]
        attempts_this_call = 0
        while not self.quota() and (max_attempts is None or attempts_this_call < max_attempts):
            rec = next_queue(self.db, kind)
            if not rec:
                return
            url = rec[0]
            # Count each candidate even if its fetch/parser fails. A probe
            # never silently walks the whole queue on parsing errors.
            attempts_this_call += 1
            try:
                html = self.get(url)
            except RequestBudgetExhausted:
                return
            except (CrawlHaltedError, PermissionError) as exc:
                record_failure(self.args.failures, url, kind, exc)
                raise
            except MissingPageError as exc:
                set_status(self.db, url, "missing", str(exc))
                self.errors += 1
                record_failure(self.args.failures, url, kind, exc)
                self.consecutive_errors = 0
                continue
            except TemporaryFetchError as exc:
                set_status(self.db, url, "failed", str(exc))
                self.errors += 1
                self.consecutive_errors += 1
                record_failure(self.args.failures, url, kind, exc)
                logging.warning("Temporary error (%d consecutive): %s", self.consecutive_errors, url)
                if self.consecutive_errors >= self.args.max_consecutive_errors:
                    raise CrawlHaltedError("Too many consecutive errors; stop to protect the site")
                continue
            self.consecutive_errors = 0
            try:
                if kind == "experience":
                    item = parse_experience(html, url)
                    save_review(self.db, item)
                    if "companies" in self.enabled and item.get("company_url"):
                        enqueue(self.db, item["company_url"], "company")
                elif kind == "company":
                    save_profile(self.db, parse_company(html, url))
                else:
                    save_article(self.db, parse_blog(html, url))
            except ValueError as exc:
                # A page that does not match our parser is *not* evidence that
                # the source URL is missing. Hold it for review, and stop after
                # a small consecutive sample instead of hammering thousands.
                set_status(self.db, url, "needs_review", "parse error: " + str(exc))
                self.errors += 1
                self.parse_errors_in_row += 1
                record_failure(self.args.failures, url, "parse_" + kind, exc)
                logging.warning("Unrecognized %s HTML (%d consecutive): %s (%s)",
                                kind, self.parse_errors_in_row, url, exc)
                if self.parse_errors_in_row >= self.args.max_consecutive_parse_errors:
                    raise CrawlHaltedError(
                        f"{kind}: {self.parse_errors_in_row} consecutive unexpected pages; "
                        "parser or access response needs inspection. No more requests."
                    ) from exc
                continue
            except sqlite3.Error as exc:
                # An actual storage fault must halt immediately, not consume
                # an entire remote queue as if the HTML were malformed.
                raise CrawlHaltedError(f"Database write failed for {url}: {exc}") from exc
            self.parse_errors_in_row = 0
            set_status(self.db, url, "done")
            self.added += 1
            if self.added == 1 or self.added % 25 == 0:
                logging.info("New documents: %d, HTTP logical requests: %d, last: %s", self.added, self.requests, url)

    def crawl_section(self, section: str) -> None:
        kind = SCOPES[section]
        self.db.execute("INSERT OR IGNORE INTO site_listings (section, next_page, updated_utc) VALUES (?,1,?)",
                        (section, utc_now()))
        self.db.commit()
        # Always empty pending queue before moving listing cursor (resume after Ctrl+C).
        self.process_queue(section)
        while not self.quota():
            state = self.db.execute("SELECT next_page, last_page, completed FROM site_listings WHERE section=?", (section,)).fetchone()
            page, last_page, completed = state
            if completed:
                logging.info("%s listings completed", section)
                break
            if page > self.args.max_pages_per_section:
                logging.warning("Reached max pages for %s (%d). Not marked complete.", section, page-1)
                break
            url = BASE + "/" + section + "?" + urlencode({"page": page})
            try:
                html = self.get(url)
            except RequestBudgetExhausted:
                break
            except (CrawlHaltedError, PermissionError) as exc:
                record_failure(self.args.failures, url, "listing_" + section, exc)
                raise
            except (TemporaryFetchError, MissingPageError) as exc:
                record_failure(self.args.failures, url, "listing_" + section, exc)
                self.errors += 1
                raise CrawlHaltedError(
                    f"{section} listing unavailable; cursor unchanged; "
                    "not moving to the next scope"
                ) from exc
            found = detail_links(html, kind)
            if not found:
                self.errors += 1
                record_failure(self.args.failures, url, "listing_empty", ValueError("Empty/unrecognized listing page"))
                raise CrawlHaltedError(
                    f"{section} listing page {page} has no recognizable links; "
                    "cursor unchanged and no other scope will be crawled"
                )
            for link in found:
                enqueue(self.db, link, kind)
            pages = page_count(html, section, page)
            if pages is not None:
                last_page = max(last_page or 0, pages)
            completed = int(last_page is not None and page >= last_page)
            self.db.execute("""UPDATE site_listings SET next_page=?,last_page=?,completed=?,updated_utc=?
                            WHERE section=?""", (page+1, last_page, completed, utc_now(), section))
            self.db.commit()
            logging.info("%s listing %d%s, found=%d, queue pending=%d", section, page,
                         "/"+str(last_page) if last_page else "", len(found),
                         self.db.execute("SELECT count(*) FROM site_queue WHERE kind=? AND status='pending'", (kind,)).fetchone()[0])
            self.process_queue(section)
            if completed:
                break

    def run(self):
        for section in self.enabled:
            if self.quota():
                break
            if section == "companies" and getattr(self.args, "company_probe_limit", 0):
                # Strict operator opt-in. Probe existing pending company URLs;
                # do not scan listings, requeue historical failures or bypass
                # robots/403/429 handling. A small number of writes are possible
                # only for successfully parsed profiles.
                logging.warning("LIMITED company probe: up to %d queued URLs; "
                                "historical failed URLs remain untouched",
                                getattr(self.args, "company_probe_limit", 0))
                self.process_queue(section, max_attempts=getattr(self.args, "company_probe_limit", 0))
                continue
            if section == "companies":
                # Historical v0.4 mass-failures (no h1) must not be retried or
                # ignored as though the parser were validated.
                broken = self.db.execute("""SELECT count(*) FROM site_queue
                    WHERE kind='company' AND status IN ('failed', 'needs_review')
                      AND (last_error LIKE '%heading h1%' OR last_error LIKE '%parse error%')""").fetchone()[0]
                successes = self.db.execute("SELECT count(*) FROM company_profiles").fetchone()[0]
                if broken >= 10 and successes == 0:
                    raise CrawlHaltedError(
                        f"Company pages disabled: {broken} prior parser failures and zero valid profiles. "
                        "Inspect saved HTML and fix parser before retrying; use --scope experiences for reviews."
                    )
            logging.info("Starting %s", section)
            self.crawl_section(section)
        return self.added


def summary(db) -> dict:
    result = {}
    for table in ("reviews", "company_profiles", "blog_articles"):
        result[table] = db.execute("SELECT count(*) FROM " + table).fetchone()[0]
    for section, next_page, last_page, finished in db.execute("SELECT section,next_page,last_page,completed FROM site_listings"):
        result["listing_" + section + "_complete"] = bool(finished)
        result["listing_" + section + "_next_page"] = next_page
        result["listing_" + section + "_last_page"] = last_page
    for kind, status, n in db.execute("SELECT kind,status,count(*) FROM site_queue GROUP BY kind,status"):
        result[kind + "_" + status] = n
    return result


def diagnostic_summary(db: sqlite3.Connection) -> dict:
    """Offline diagnosis of queue health; never contacts tajrobewiki.com."""
    result = summary(db)
    problems = {}
    for kind, status, count in db.execute("""
            SELECT kind, status, COUNT(*) FROM site_queue
            WHERE status IN ('failed', 'needs_review', 'missing')
            GROUP BY kind, status ORDER BY kind, status"""):
        problems[f"{kind}_{status}"] = count
    result["issues_by_type"] = problems
    result["company_missing_h1"] = db.execute("""SELECT count(*) FROM site_queue
        WHERE kind='company' AND last_error LIKE '%heading h1%'""").fetchone()[0]
    result["company_recent_error_samples"] = [
        {"url": url, "status": status, "error": (error or "")[:400]}
        for url, status, error in db.execute("""SELECT url,status,last_error FROM site_queue
            WHERE kind='company' AND status IN ('failed','needs_review')
            ORDER BY updated_utc DESC LIMIT 5""")
    ]
    result["advice"] = (
        "Do not retry company URLs while company parsing is unverified. "
        "HTTP 403 is an access stop, not a retry signal. "
        "Analyze failed page markup offline; preserve data and use "
        "--scope experiences only after confirming access is allowed."
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope", choices=["experiences", "companies", "blog", "all"], default="experiences")
    p.add_argument("--max-items", type=int, default=100, help="new detail pages per run (0=unlimited)")
    p.add_argument("--max-requests", type=int, default=150, help="max logical HTTP fetches per run (0=unlimited)")
    p.add_argument("--max-pages-per-section", type=int, default=10000)
    p.add_argument("--pause", type=float, default=12.0, help="minimum delay in seconds (>=3)")
    p.add_argument("--retries", type=int, default=1)
    p.add_argument("--retry-wait", type=float, default=30.0)
    p.add_argument("--max-consecutive-errors", type=int, default=2)
    p.add_argument("--max-consecutive-parse-errors", type=int, default=2)
    p.add_argument("--retry-failed", action="store_true", help="requeue transient or parser failures")
    p.add_argument("--company-probe-limit", type=int, default=0,
                   help="operator-approved bounded test of 1-3 *pending* company URLs; "
                        "no listing scans or mass retries")
    p.add_argument("--db", type=Path, default=Path("data/tajrobewiki.db"))
    p.add_argument("--failures", type=Path, default=Path("data/failed_requests.jsonl"))
    p.add_argument("--status", action="store_true", help="print DB summary; no HTTP")
    p.add_argument("--diagnose", action="store_true", help="offline queue error diagnosis; no HTTP")
    p.add_argument("--inspect-company-html", type=Path,
                   help="inspect browser-saved company HTML with the actual v0.6 parser; no HTTP or DB changes")
    p.add_argument("--inspect-company-url", default=BASE + "/companies/offline-sample",
                   help="source URL label for --inspect-company-html (no fetch)")
    p.add_argument("--dry-run", action="store_true", help="print crawl plan; no HTTP")
    p.add_argument("--permission-confirmed", action="store_true", help="confirm independent authorization to crawl/reuse content")
    args = p.parse_args()
    if args.max_items < 0 or args.max_requests < 0 or not (1 <= args.max_pages_per_section <= 100000):
        p.error("limits must be non-negative (page limit >=1)")
    if args.pause < 3 or args.retry_wait < 10 or not (0 <= args.retries <= 2) or args.max_consecutive_errors < 1 or args.max_consecutive_parse_errors < 1:
        p.error("pause>=3, retry-wait>=10, retries=0..2, consecutive errors>=1")
    if not (0 <= args.company_probe_limit <= 3):
        p.error("--company-probe-limit must be in 0..3")
    if args.company_probe_limit and (
        args.scope != "companies" or args.retry_failed or
        not 1 <= args.max_items <= 3 or
        not 1 <= args.max_requests <= 6 or args.pause < 12 or
        args.status or args.diagnose or args.dry_run or args.inspect_company_html
    ):
        p.error("Company probe: use --scope companies --company-probe-limit 1..3 "
                "--max-items 3 --max-requests 4 --pause 12; "
                "no --retry-failed or other modes")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.dry_run:
        print(json.dumps({"scope":args.scope,"max_items":args.max_items,
                          "max_requests":args.max_requests,"pause":args.pause,
                          "data_unchanged":True}, ensure_ascii=False, indent=2))
        return
    if args.inspect_company_html:
        if not args.inspect_company_html.is_file():
            p.error("HTML file not found: " + str(args.inspect_company_html))
        print(json.dumps(inspect_saved_company_html(args.inspect_company_html,
                                                    args.inspect_company_url),
                         ensure_ascii=False, indent=2))
        return
    if not (args.status or args.diagnose) and not args.permission_confirmed:
        p.error("Only use this program with appropriate collection/reuse permission; supply --permission-confirmed")
    db = prepare_db(args.db)
    ensure_archive_tables(db)
    try:
        if args.status:
            print(json.dumps(summary(db), ensure_ascii=False, indent=2))
            return
        if args.diagnose:
            print(json.dumps(diagnostic_summary(db), ensure_ascii=False, indent=2))
            return
        if args.retry_failed:
            # Scope the retry. Never mass-requeue company parser failures;
            # especially not after an HTTP 403 or thousands of no-h1 pages.
            retry_kind = SCOPES.get(args.scope)
            if retry_kind is None or retry_kind == "company":
                p.error("--retry-failed only supports --scope experiences or --scope blog. "
                        "Company failures require parser diagnosis first.")
            db.execute("UPDATE site_queue SET status='pending',last_error=NULL WHERE kind=? AND status='failed'", (retry_kind,))
            db.commit()
        fetch = PoliteFetcher(args.pause, retries=args.retries, retry_wait=args.retry_wait)
        try:
            fetch.load_robots()
        except RuntimeError as exc:
            logging.error("Cannot verify robots policy, no crawl performed: %s", exc)
            return
        delay = fetch.rules.crawl_delay(fetch.session.headers.get("User-Agent", ""))
        if isinstance(delay, (int, float)) and delay > fetch.pause:
            fetch.pause = float(delay)
            logging.info("Respecting robots Crawl-delay: %.0fs", fetch.pause)
        job = SiteArchive(db, fetch, args)
        try:
            job.run()
        except (CrawlHaltedError, PermissionError) as exc:
            logging.error("Stopped by access/policy/sustained failures: %s", exc)
        except KeyboardInterrupt:
            logging.warning("Interrupted by operator; checkpoint preserved")
        finally:
            export_jsonl(db, Path("data/reviews.jsonl"))
            export_table(db, "company_profiles", Path("data/companies.jsonl"))
            export_table(db, "blog_articles", Path("data/blog_articles.jsonl"))
            logging.info("Run: new=%d fetches=%d failures=%d", job.added, job.requests, job.errors)
            print(json.dumps(summary(db), ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
