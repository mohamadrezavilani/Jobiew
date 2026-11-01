"""Pure helpers for offline five-criteria research exports; no Django dependency."""
from __future__ import annotations
import re

# Conservative contact masking. Proper names and allegations are NOT automatically anonymized.
_EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?!\w)', re.I)
_IR_PHONE = re.compile(r'(?<!\d)(?:\+98|0098|0)?\s*9(?:[\s\-]?\d){9}(?!\d)')


def redact_contacts(value: str):
    """Return (partially redacted text, was_modified). Never modify source DB."""
    value = value or ''
    clean = _EMAIL.sub('[EMAIL_REDACTED]', value)
    clean = _IR_PHONE.sub('[PHONE_REDACTED]', clean)
    return clean, clean != value


def choose_company_bundles(grouped: dict, *, limit: int, minimum_company_reviews: int,
                           max_per_company: int, already_count: dict | None = None):
    """Choose multiple reviews/company (not one/company), prefer richer company coverage.

    grouped: {company_id: [lightweight candidates with pk]}; already_count from imported five_v1.
    Explicit pure function so users can test selection without a database.
    """
    already_count = already_count or {}
    if limit < 1 or minimum_company_reviews < 1 or max_per_company < 1:
        raise ValueError('Positive limits required')
    groups = []
    for company_id, rows in grouped.items():
        if not rows:
            continue
        total = len(rows) + already_count.get(company_id, 0)
        if total < minimum_company_reviews:
            continue
        sorted_rows = sorted(rows, key=lambda row: (row['pk'], row['source_url']))
        groups.append((company_id, sorted_rows, total))
    # Prefer companies with more currently usable independent work narratives;
    # tie break deterministically by ID. No claim of actual author independence.
    groups.sort(key=lambda item: (-item[2], -len(item[1]), str(item[0])))
    chosen = []
    for _company_id, rows, _total in groups:
        slots = min(max_per_company, limit - len(chosen))
        chosen.extend(rows[:slots])
        if len(chosen) >= limit:
            break
    return chosen
