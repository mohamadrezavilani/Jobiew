"""Conservative public-page crawler for TajrobeWiki (pilot, no login or bypass)."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://tajrobewiki.com"
INDUSTRY = "کامپیوتر، فناوری اطلاعات و اینترنت"
UA = "TajrobeResearchCrawler/0.1 (public-pages-only; permission-checked research pilot)"
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
MONTHS = "فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند"
DATE_RE = re.compile(rf"\b\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}\b")
PERIOD_RE = re.compile(rf"(?:{MONTHS})\s+\d{{4}}\s+تا\s+(?:{MONTHS})\s+\d{{4}}")
SCORE_RE = re.compile(r"امتیاز\s*([\d.,٫]+)\s*از\s*[۵5]")
DIMENSIONS = {
    "فرهنگ سازمانی": "culture",
    "مدیریت": "management",
    "حقوق و مزایا": "compensation",
    "تعادل کار-زندگی": "work_life_balance",
    "تعادل کار و زندگی": "work_life_balance",
    "فرصت رشد": "career_growth",
    "توصیه به دیگران": "recommendation",
}
STOP_LABELS = {"نقاط قوت", "نقاط ضعف", "امتیاز چندمعیاره", "مفید بود", "گزارش", "تجربه‌های مشابه", "ثبت تجربه شما"}
IGNORE_LABELS = {"ادامه", "اشتراک", "مشاهده پروفایل شرکت"}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("ي", "ی").replace("ك", "ک")).strip()


def western(text: str) -> str:
    return text.translate(DIGITS).replace("٫", ".").replace("٬", "")


def rating(text: str) -> float | None:
    t = western(text).strip()
    m = re.fullmatch(r"(\d(?:[.,]\d+)?)", t)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value if 0 <= value <= 5 else None


def same_site_url(href: str, prefix: str) -> str | None:
    result = urljoin(BASE, href)
    parsed = urlsplit(result)
    if parsed.hostname not in {"tajrobewiki.com", "www.tajrobewiki.com"}:
        return None
    if not parsed.path.startswith(prefix) or parsed.path.rstrip("/") == prefix.rstrip("/"):
        return None
    return urlunsplit(("https", "tajrobewiki.com", parsed.path.rstrip("/"), "", ""))


def listing_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []
    for link in soup.select('a[href*="/experiences/"]'):
        url = same_site_url(link.get("href", ""), "/experiences/")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _visible_lines(soup: BeautifulSoup) -> list[str]:
    main = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    for tag in main.select("script, style, noscript, svg, nav, footer, aside, form"):
        tag.decompose()
    return [norm(v) for v in main.stripped_strings if norm(v)]


def _section(lines: list[str], name: str) -> list[str]:
    try:
        index = lines.index(name)
    except ValueError:
        return []
    stop = index + 1
    while stop < len(lines) and lines[stop] not in STOP_LABELS:
        stop += 1
    return [line for line in lines[index + 1:stop] if line not in IGNORE_LABELS]


def _is_heading_or_meta(line: str, title: str) -> bool:
    if line == title or line in IGNORE_LABELS:
        return True
    if line.startswith(("تجربه کاری", "تجربه مصاحبه", "امتیاز ", "کاربر ناشناس", "مصاحبه ")):
        return True
    if line.startswith("–") or re.match(r"^[\d۰-۹٠-٩.,٫]+\s*[–-]", line):
        return True
    if rating(line) is not None:
        return True
    if DATE_RE.fullmatch(line):
        return True
    return False


def parse_experience(html: str, url: str) -> dict[str, Any]:
    """Parse an individual experience page. Raises ValueError for unrecognized markup."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    h1 = main.find("h1")
    if not h1:
        raise ValueError("no h1 found; layout may have changed")
    title = norm(h1.get_text(" ", strip=True))
    lines = _visible_lines(soup)
    if title not in lines:
        raise ValueError("review title missing from readable content")
    title_idx = lines.index(title)
    before_body = lines[:title_idx + 1]
    company_name: str | None = None
    company_url: str | None = None
    for a in main.select('a[href*="/companies/"]'):
        found = same_site_url(a.get("href", ""), "/companies/")
        if found:
            company_url = found
            company_name = norm(a.get_text(" ", strip=True)) or None
            break
    # Some templates put the company breadcrumb outside <main>.
    if not company_url:
        for a in soup.select('a[href*="/companies/"]'):
            found = same_site_url(a.get("href", ""), "/companies/")
            if found:
                company_url = found
                company_name = norm(a.get_text(" ", strip=True)) or None
                break
    subhead = " ".join(norm(h.get_text(" ", strip=True)) for h in main.find_all("h2", limit=3))
    context = " ".join(before_body[-8:]) + " " + subhead
    review_type = "interview" if "مصاحبه" in context and "تجربه کاری" not in context else "work"

    # The main prose is located between the review heading/score and the first detail section.
    tail = lines[title_idx + 1:]
    cutoff = next((i for i, line in enumerate(tail) if line in STOP_LABELS), len(tail))
    preamble = tail[:cutoff]
    body_parts = [line for line in preamble if not _is_heading_or_meta(line, title)]
    body_text = "\n".join(body_parts).strip()
    if len(body_text) < 12:
        raise ValueError("no substantial review body found; layout may have changed")

    page_text = " ".join(lines[: min(len(lines), title_idx + 20)])
    dates = DATE_RE.findall(page_text)
    published = dates[0] if dates else None
    employment_match = PERIOD_RE.search(page_text)
    employment_period = employment_match.group(0) if employment_match else None
    score_match = SCORE_RE.search(western(page_text))
    overall_rating = rating(score_match.group(1)) if score_match else None
    # Sometimes score is rendered as a standalone value followed by job title.
    if overall_rating is None:
        for line in preamble[:5]:
            match = re.match(r"^([۰-۹0-9.,٫]+)\s*[–-]", line)
            if match:
                overall_rating = rating(match.group(1))
                break

    job_title = None
    job_match = re.search(r"تجربه کاری\s+(.+?)\s+در\s+.+", subhead)
    if job_match:
        job_title = job_match.group(1).strip()
    if not job_title:
        job_match = re.search(r"تجربه مصاحبه\s+(.+?)\s+در\s+.+", subhead)
        if job_match:
            job_title = job_match.group(1).strip()
    dimensions: dict[str, float] = {}
    dim_section = _section(lines, "امتیاز چندمعیاره")
    for i, key in enumerate(dim_section[:-1]):
        if key in DIMENSIONS:
            value = rating(dim_section[i + 1])
            if value is not None:
                dimensions[DIMENSIONS[key]] = value
    if not company_url:
        raise ValueError("company permalink not found")
    return {
        "source": "tajrobewiki.com",
        "url": url,
        "company": company_name,
        "company_url": company_url,
        "title": title,
        "review_type": review_type,
        "job_title": job_title,
        "published_jalali": published,
        "employment_period_jalali": employment_period,
        "rating_5": overall_rating,
        "dimension_ratings_5": dimensions,
        "pros": _section(lines, "نقاط قوت"),
        "cons": _section(lines, "نقاط ضعف"),
        "body": body_text,
        "crawled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


class CrawlHaltedError(RuntimeError):
    """Policy/access problem: stop all network requests for this run."""


class TemporaryFetchError(RuntimeError):
    """A temporarily unavailable page: skip it and try again on a future run."""


class MissingPageError(RuntimeError):
    """A review was deleted or its URL is no longer available."""


class PoliteFetcher:
    def __init__(self, pause: float, retries: int = 1, retry_wait: float = 20.0):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.5"})
        self.pause = max(pause, 3.0)
        self.retries = max(0, min(retries, 2))
        self.retry_wait = max(retry_wait, 10.0)
        self.last_request: float | None = None
        self.rules = RobotFileParser()
        self.rules_ready = False

    def _throttle(self) -> None:
        if self.last_request is not None:
            wait = self.pause + random.uniform(0.0, 1.0) - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
        self.last_request = time.monotonic()

    def get(self, url: str) -> str:
        if not self.rules_ready:
            raise RuntimeError("robots policy must be loaded before requests")
        if not self.rules.can_fetch(UA, url):
            raise PermissionError(f"robots.txt disallows {url}")

        # GET is read-only, but repeat at most twice and back off to avoid
        # amplifying temporary server problems. 403/429 are NEVER retried.
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                r = self.session.get(url, timeout=(10, 25), allow_redirects=False)
            except requests.RequestException as exc:
                reason = f"{type(exc).__name__}: {exc}"
            else:
                status = r.status_code
                if status in {301, 302, 303, 307, 308, 401, 403, 429}:
                    raise CrawlHaltedError(f"stopping on HTTP {status} for {url}; no bypass attempts")
                if status in {404, 410}:
                    raise MissingPageError(f"HTTP {status}: {url}")
                if 500 <= status <= 599:
                    reason = f"HTTP {status}"
                else:
                    if status >= 400:
                        raise CrawlHaltedError(f"stopping on unexpected HTTP {status} for {url}")
                    if "text/html" not in r.headers.get("Content-Type", "text/html").lower():
                        raise CrawlHaltedError(f"unexpected content type at {url}")
                    return r.text

            if attempt < self.retries:
                delay = self.retry_wait * (2 ** attempt)
                logging.warning("Temporary fetch error %s (%s); retry %d/%d in %.0fs",
                                url, reason, attempt + 1, self.retries, delay)
                time.sleep(delay)
            else:
                raise TemporaryFetchError(f"{url}: {reason}; exhausted {self.retries + 1} attempt(s)")
        raise AssertionError("unreachable")

    def load_robots(self) -> None:
        self._throttle()
        try:
            r = self.session.get(BASE + "/robots.txt", timeout=(10, 20), allow_redirects=False)
        except requests.RequestException as exc:
            raise RuntimeError("robots.txt could not be checked: crawl halted") from exc
        if r.status_code == 200:
            self.rules.parse(r.text.splitlines())
            self.rules_ready = True
            logging.info("Loaded robots.txt (%d bytes)", len(r.content))
            return
        if r.status_code in {404, 410}:
            # The operator has separately confirmed authorization and there is no robots file.
            self.rules.parse([])
            self.rules_ready = True
            logging.warning("No robots.txt (HTTP %d); verify site permission separately", r.status_code)
            return
        raise RuntimeError(f"robots.txt HTTP {r.status_code}: cannot verify crawler access; stopping")


def record_failure(dest: Path, url: str, stage: str, error: Exception) -> None:
    """Keep a trace of skipped pages; no requests are made from this log."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as out:
        out.write(json.dumps({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "url": url,
            "error": str(error),
        }, ensure_ascii=False) + "\n")


def prepare_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            url TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            company TEXT,
            company_url TEXT,
            title TEXT NOT NULL,
            review_type TEXT NOT NULL,
            job_title TEXT,
            published_jalali TEXT,
            employment_period_jalali TEXT,
            rating_5 REAL,
            dimension_ratings_json TEXT NOT NULL,
            pros_json TEXT NOT NULL,
            cons_json TEXT NOT NULL,
            body TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            crawled_at_utc TEXT NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS ix_reviews_company ON reviews(company_url)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_reviews_type ON reviews(review_type)")
    db.commit()
    return db


def save_review(db: sqlite3.Connection, item: dict[str, Any]) -> None:
    content_sha256 = hashlib.sha256((item["title"] + "\n" + item["body"]).encode("utf-8")).hexdigest()
    db.execute("""
        INSERT INTO reviews (
            url, source, company, company_url, title, review_type, job_title,
            published_jalali, employment_period_jalali, rating_5,
            dimension_ratings_json, pros_json, cons_json, body,
            content_sha256, crawled_at_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET
            company=excluded.company,
            company_url=excluded.company_url,
            title=excluded.title,
            review_type=excluded.review_type,
            job_title=excluded.job_title,
            published_jalali=excluded.published_jalali,
            employment_period_jalali=excluded.employment_period_jalali,
            rating_5=excluded.rating_5,
            dimension_ratings_json=excluded.dimension_ratings_json,
            pros_json=excluded.pros_json,
            cons_json=excluded.cons_json,
            body=excluded.body,
            content_sha256=excluded.content_sha256,
            crawled_at_utc=excluded.crawled_at_utc
    """, (
        item["url"], item["source"], item["company"], item["company_url"],
        item["title"], item["review_type"], item["job_title"],
        item["published_jalali"], item["employment_period_jalali"],
        item["rating_5"], json.dumps(item["dimension_ratings_5"], ensure_ascii=False),
        json.dumps(item["pros"], ensure_ascii=False),
        json.dumps(item["cons"], ensure_ascii=False), item["body"],
        content_sha256, item["crawled_at_utc"]
    ))
    db.commit()


def export_jsonl(db: sqlite3.Connection, dest: Path) -> int:
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM reviews ORDER BY crawled_at_utc, url").fetchall()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as out:
        for row in rows:
            entry = dict(row)
            for key, target in (("dimension_ratings_json", "dimension_ratings_5"),
                                ("pros_json", "pros"), ("cons_json", "cons")):
                entry[target] = json.loads(entry.pop(key))
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Crawl selected TajrobeWiki public reviews (authorized pilot)")
    p.add_argument("--max-pages", type=int, default=2, help="listing pages, max 20 reviews per page")
    p.add_argument("--max-reviews", type=int, default=20, help="max newly fetched reviews")
    p.add_argument("--pause", type=float, default=8.0, help="min seconds between requests (>=3)")
    p.add_argument("--retries", type=int, default=1, help="extra tries on temporary errors; 0 to 2")
    p.add_argument("--retry-wait", type=float, default=20.0, help="backoff before retry in seconds (>=10)")
    p.add_argument("--max-consecutive-errors", type=int, default=2,
                   help="stop politely after this many consecutive review fetch errors")
    p.add_argument("--failures", type=Path, default=Path("data/failed_requests.jsonl"),
                   help="append failed URLs and error details for diagnosis")
    p.add_argument("--city", default="تهران")
    p.add_argument("--industry", default=INDUSTRY)
    p.add_argument("--type", choices=["work", "interview"], default="work")
    p.add_argument("--db", type=Path, default=Path("data/tajrobewiki.db"))
    p.add_argument("--jsonl", type=Path, default=Path("data/reviews.jsonl"))
    p.add_argument("--refresh", action="store_true", help="revisit already-stored reviews")
    p.add_argument("--dry-run", action="store_true", help="show plan without sending requests")
    p.add_argument("--permission-confirmed", action="store_true", help="confirm authorized collection and intended reuse")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (1 <= args.max_pages <= 1000 and 1 <= args.max_reviews <= 100000):
        p.error("max-pages and max-reviews must be positive and within safety bounds")
    if not (0 <= args.retries <= 2 and args.retry_wait >= 10 and args.max_consecutive_errors >= 1):
        p.error("retries must be 0..2, retry-wait >= 10, max-consecutive-errors >= 1")
    params = {"type": args.type, "city": args.city, "industry": args.industry}
    preview = BASE + "/experiences?" + urlencode({**params, "page": 1})
    if args.dry_run:
        print("Start listing:", preview)
        print("Limits:", args.max_pages, "listing pages;", args.max_reviews, "review pages")
        print("No requests sent. For collection, first confirm authorization and then use --permission-confirmed")
        return
    if not args.permission_confirmed:
        p.error("confirm your right to collect/reuse website content; use --permission-confirmed")

    db = prepare_db(args.db)
    fetch = PoliteFetcher(args.pause, retries=args.retries, retry_wait=args.retry_wait)
    processed = 0
    failed = 0
    consecutive_errors = 0
    seen_this_run: set[str] = set()
    try:
        try:
            fetch.load_robots()
        except RuntimeError as exc:
            logging.error("robots.txt policy check failed; no crawling: %s", exc)
            return
        stop_crawl = False
        for page in range(1, args.max_pages + 1):
            list_url = BASE + "/experiences?" + urlencode({**params, "page": page})
            try:
                html = fetch.get(list_url)
            except TemporaryFetchError as exc:
                failed += 1
                record_failure(args.failures, list_url, "listing", exc)
                logging.error("Listing unavailable; stopping safely: %s", exc)
                break
            except (CrawlHaltedError, PermissionError) as exc:
                record_failure(args.failures, list_url, "listing", exc)
                logging.error("Access/policy stop: %s", exc)
                break
            urls = listing_urls(html)
            logging.info("Listing %d: %d unique review links", page, len(urls))
            if not urls:
                logging.warning("No experience links: stop to inspect HTML/selectors")
                break
            for url in urls:
                if url in seen_this_run:
                    continue
                seen_this_run.add(url)
                if not args.refresh and db.execute("SELECT 1 FROM reviews WHERE url=?", (url,)).fetchone():
                    continue
                if processed >= args.max_reviews:
                    break
                try:
                    doc = fetch.get(url)
                except (TemporaryFetchError, MissingPageError) as exc:
                    failed += 1
                    consecutive_errors += 1
                    record_failure(args.failures, url, "review", exc)
                    logging.warning("Skipped unavailable review (%d consecutive): %s",
                                    consecutive_errors, exc)
                    if consecutive_errors >= args.max_consecutive_errors:
                        logging.error("Too many consecutive fetch errors; stop to avoid stressing site")
                        stop_crawl = True
                        break
                    continue
                except (CrawlHaltedError, PermissionError) as exc:
                    record_failure(args.failures, url, "review", exc)
                    logging.error("Access/policy stop: %s", exc)
                    stop_crawl = True
                    break
                # A successful network response resets the transient error counter.
                consecutive_errors = 0
                try:
                    item = parse_experience(doc, url)
                except ValueError as exc:
                    failed += 1
                    record_failure(args.failures, url, "parse", exc)
                    logging.error("Parser failed: %s (%s)", url, exc)
                    continue
                if item["review_type"] != args.type:
                    logging.warning("Skipped unexpected review type: %s", url)
                    continue
                save_review(db, item)
                processed += 1
                logging.info("Saved %d: %s | %s", processed, item["company"], url)
            if stop_crawl or processed >= args.max_reviews:
                break
    finally:
        count = export_jsonl(db, args.jsonl)
        logging.info("Saved this run: %d; skipped/failed: %d; total DB/export rows: %d",
                     processed, failed, count)
        db.close()


if __name__ == "__main__":
    main()
