"""Pure contracts for bounded, resumable and non-publishing dual-six execution.

No database access, network, or source text persists in this module.
"""
import hashlib
import re

BULK_VERSION = 'jobiew_dual6_bounded_bulk_v215'
MAX_PAID_PER_INVOCATION = 10
MODEL_RE = re.compile(r'claude-[a-z0-9-]{4,90}\Z')
DIGEST_RE = re.compile(r'[0-9a-fA-F]{64}\Z')


def validate_budget(limit, after_id):
    if type(limit) is not int or not 1 <= limit <= MAX_PAID_PER_INVOCATION:
        raise ValueError('limit must be between 1 and 10')
    if type(after_id) is not int or after_id < 0:
        raise ValueError('after-id must be a nonnegative integer')


def deterministic_run_id(source_id, source_digest, model):
    if type(source_id) is not int or source_id < 1:
        raise ValueError('invalid experience identifier')
    if not isinstance(source_digest, str) or not DIGEST_RE.fullmatch(source_digest):
        raise ValueError('invalid source digest')
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        raise ValueError('invalid model identifier')
    data = f'{BULK_VERSION}|{source_id}|{source_digest}|{model}'.encode('utf-8')
    return 'dual6v215_' + hashlib.sha256(data).hexdigest()


def choose_batch(rows, *, limit, after_id=0):
    """Select a bounded batch without raw text or an external request.

    Every row: (positive source_id, work|interview, reason). A previous failed
    analysis never enters the candidate list again unless deliberately reviewed
    outside this workflow. Re-run from cursor=0 after eligibility changes.
    """
    validate_budget(limit, after_id)
    batch = []
    blockers = {}
    last = after_id
    scanned = 0
    prev = after_id
    for pk, kind, reason in rows:
        if type(pk) is not int or pk <= prev:
            raise ValueError('queryset must be sorted by strictly increasing IDs')
        if kind not in ('work','interview'):
            raise ValueError('invalid kind')
        if not isinstance(reason, str) or not reason:
            raise ValueError('missing eligibility decision')
        prev = last = pk
        scanned += 1
        if reason == 'ready':
            batch.append({'experience_id': pk, 'kind': kind})
            if len(batch) >= limit:
                break
        else:
            blockers[reason] = blockers.get(reason, 0) + 1
    return {'scanned': scanned, 'selected': batch, 'selected_count': len(batch),
            'last_scanned_id': last, 'blockers_in_scan': blockers,
            'per_run_paid_call_cap': limit}


def sanitized_failure_code(exc):
    """Never leak prompt, story, full external response, or connection secrets."""
    from_name = type(exc).__name__
    detail = str(exc)
    if from_name == 'ProposalError' and re.fullmatch(r'[A-Z][A-Z0-9_]{2,90}', detail):
        return detail
    if isinstance(exc, RuntimeError) and re.fullmatch(
            r'(?:ANTHROPIC|MODEL_RESPONSE)_[A-Z0-9_]{2,90}', detail):
        return detail
    return from_name[:90]
