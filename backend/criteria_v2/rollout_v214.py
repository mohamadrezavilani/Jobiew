"""Pure, fail-closed rollout eligibility for the independent Jobiew 6+6 framework.

Never equate a pilot proposal with a human approved analysis; never infer
copyright, company attribution, classification or quality approval from text.
This module does not touch a database, files, an API, or model inference.
"""
from __future__ import annotations

from .registry import VERSIONS

MIN_CHARS = 50
MAX_CHARS = 8000

REASONS = (
    'source_kind_invalid', 'copyright_not_approved', 'attribution_not_verified',
    'known_duplicate', 'source_digest_invalid', 'text_out_of_range',
    'classification_not_confirmed', 'already_evaluated', 'ready',
)


def decide(*, kind, copyright_review, company_attribution_status,
           independence_status, source_digest, story_length,
           classification_decision, classification_digest, existing_analysis):
    """One dominant actionable reason per experience, in priority order.

    `existing_analysis` means *any* existing current-source v2 analysis,
    including unverified pilots, to prevent accidental duplicate paid calls.
    The preview remains conservative even when old outcomes were failures.
    """
    if kind not in VERSIONS:
        return 'source_kind_invalid'
    if copyright_review != 'approved':
        return 'copyright_not_approved'
    if company_attribution_status != 'verified':
        return 'attribution_not_verified'
    if independence_status == 'duplicate':
        return 'known_duplicate'
    if not isinstance(source_digest, str) or len(source_digest) != 64 or any(
            c not in '0123456789abcdefABCDEF' for c in source_digest):
        return 'source_digest_invalid'
    if not isinstance(story_length, int) or not MIN_CHARS <= story_length <= MAX_CHARS:
        return 'text_out_of_range'
    if classification_decision != 'confirmed' or classification_digest != source_digest:
        return 'classification_not_confirmed'
    if existing_analysis:
        return 'already_evaluated'
    return 'ready'


def summarize(records, *, cap=20, after_id=0):
    """Summarize `(id, kind, decision_reason)` without raw texts.

    The input is ordered, with no duplicate IDs. Only ready record IDs appear in
    bounded preview; no text, URL or source names are ever included.
    """
    if type(cap) is not int or not 1 <= cap <= 100:
        raise ValueError('cap must be 1..100')
    if type(after_id) is not int or after_id < 0:
        raise ValueError('after_id must be >=0')
    counts = {'work': {}, 'interview': {}}
    selected = []
    seen = set()
    for pk, kind, reason in records:
        if type(pk) is not int or pk <= after_id or pk in seen:
            raise ValueError('IDs must be unique positive integers after cursor')
        if kind not in counts or reason not in REASONS:
            raise ValueError('invalid kind or reason')
        seen.add(pk)
        bucket = counts[kind]
        bucket[reason] = bucket.get(reason, 0) + 1
        if reason == 'ready' and len(selected) < cap:
            selected.append({'experience_id': pk, 'kind': kind})
    return {
        'total_inspected': len(seen), 'by_kind': counts,
        'ready_total': sum(v.get('ready', 0) for v in counts.values()),
        'next_batch': selected, 'next_batch_size': len(selected),
        'cursor_after_id': after_id, 'changes': 0,
        'external_api_calls': 0, 'publication': 'DISABLED',
    }
