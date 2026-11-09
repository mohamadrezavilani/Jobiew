"""Strict private GPT-6 checkpoint handoff adapter; pure Python, no DB/AI.

Never treat a source's pending copyright/attribution status as approved.
Every proposal remains unverified and must be kept out of public aggregates.
"""
import hashlib
import json
import re
import zipfile
from pathlib import Path

from .checkpoint_qav218 import audit, CheckpointError, strict_json, parse_jsonl

ENGINE = 'jobiew_gpt6_private_checkpoint_v218'
STATUS = 'pilot_unverified'
PROMPT = 'gpt6_checkpoint_import_v218'
MAX_ARCHIVE_BYTES = 120 * 1024 * 1024
MAX_RECORDS = 100_000


def _sha256(binary):
    return hashlib.sha256(binary).hexdigest()


def stage_run_id(row):
    """Stable across successive cumulative checkpoint ZIPs, if a proposal is unchanged."""
    payload = json.dumps(row['prediction'], ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    material = ('|'.join((ENGINE, str(row['experience_id']), str(row['company_id']),
                         row['kind'], row['source_content_sha256'], row['story_sha256'],
                         _sha256(payload)))).encode('utf-8')
    return 'cpx218_' + _sha256(material)


def load_handoff(source_path, checkpoint_path):
    """Fail closed on tampered source/checkpoint, extra outputs or bad references.

    Returns vetted rows, ledger, and QA summary. Never prints or writes stories.
    """
    source_path, checkpoint_path = Path(source_path), Path(checkpoint_path)
    for path in (source_path, checkpoint_path):
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise CheckpointError('Missing or oversize private ZIP')
    # Reject malformed or oversized archives before any decompression.
    try:
        for path in (source_path, checkpoint_path):
            with zipfile.ZipFile(path) as z:
                if len(z.infolist()) > 500:
                    raise CheckpointError('Private ZIP contains too many members')
                if sum(i.file_size for i in z.infolist()) > MAX_ARCHIVE_BYTES * 2:
                    raise CheckpointError('Private ZIP uncompressed content exceeds safety cap')
                if any(i.file_size > MAX_ARCHIVE_BYTES for i in z.infolist()):
                    raise CheckpointError('Private ZIP member exceeds safety cap')
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise CheckpointError('Missing or malformed private ZIP') from None
    try:
        summary, _ = audit(source_path, checkpoint_path)
    except (OSError, KeyError, ValueError, IndexError, TypeError, zipfile.BadZipFile) as exc:
        raise CheckpointError('Checkpoint/source audit failed: ' + type(exc).__name__) from None
    if summary['source_records'] > MAX_RECORDS or summary['publication'] != 'DISABLED':
        raise CheckpointError('Unacceptable source count or publication status')
    with zipfile.ZipFile(checkpoint_path) as z:
        cp = strict_json(z.read('checkpoint.json'))
        ledger_rows = parse_jsonl(z.read('ledger.jsonl'), 'ledger')
        ledger = {row['experience_id']: row for row in ledger_rows}
        rows = parse_jsonl(z.read('assistant_predictions.jsonl'), 'predictions')
    if (cp.get('source_rights') != 'NOT_ESTABLISHED' or
            cp.get('publication') != 'DISABLED' or
            cp.get('independent_semantic_accuracy_established') is not False):
        raise CheckpointError('Unexpected authorization, publication, or quality flags')
    if len(ledger) != len(ledger_rows) or len(ledger) != summary['source_records'] or len(rows) != summary['reviewed']:
        raise CheckpointError('Checkpoint/ledger count mismatch')
    rows.sort(key=lambda r: r['experience_id'])
    return rows, ledger, summary


def select_batch(rows, ledger, *, after_id=0, limit=100):
    """Deterministic ID cursor; duplicate-source stories are deferred, never scored twice."""
    if type(after_id) is not int or after_id < 0:
        raise ValueError('after_id must be an integer >=0')
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('limit must be in 1..500')
    selected = []
    blocked_duplicates = 0
    for row in rows:
        exp_id = row['experience_id']
        if exp_id <= after_id:
            continue
        if ledger[exp_id].get('exact_duplicate_of_experience_id') is not None:
            blocked_duplicates += 1
            continue
        selected.append(row)
        if len(selected) == limit:
            break
    return selected, blocked_duplicates


def verify_source_pair(row, exp, story):
    """Exact source-to-local database match without considering pending rights approved."""
    if (row['experience_id'] != exp.pk or row['company_id'] != exp.company_id or
        row['kind'] != exp.source_kind or
        row['source_content_sha256'] != exp.content_sha256 or
        row['story_sha256'] != _sha256(story.encode('utf-8'))):
        raise CheckpointError('SOURCE_IDENTITY_OR_CONTENT_MISMATCH')
    if (exp.copyright_review == 'blocked' or
        exp.company_attribution_status == 'rejected' or
        exp.independence_status == 'duplicate'):
        raise CheckpointError('SOURCE_EXPLICITLY_BLOCKED')
    if row.get('review_status') != 'unverified_private_proposal':
        raise CheckpointError('PROPOSAL_NOT_UNVERIFIED')
    if not re.fullmatch(r'[0-9a-f]{64}', row['story_sha256']):
        raise CheckpointError('SOURCE_STORY_DIGEST_INVALID')
    return True


def summary_only(summary, *, selected, duplicates, existing, would_insert):
    return {
        'engine': ENGINE,
        'source_total': summary['source_records'],
        'checkpoint_reviewed': summary['reviewed'],
        'checked_in_batch': len(selected),
        'checkpoint_numeric': summary['numeric_proposals'],
        'checkpoint_abstentions': summary['abstentions'],
        'previously_staged': existing,
        'would_insert': would_insert,
        'duplicate_source_skipped_in_scan': duplicates,
        'independent_quality': 'NOT_ESTABLISHED',
        'human_approval': 'NONE',
        'publication': 'DISABLED',
        'external_api_calls': 0,
        'source_text_in_report': False,
    }


def stored_scores_match(normalized, axis_scores):
    """An existing run is reusable only if ALL six stored proposals are unchanged.

    The run ID binds the original prediction; it does not protect against later
    database edits. This check must reject partial or edited axis scores.
    """
    expected = normalized.get('dimensions')
    if not isinstance(expected, dict) or len(expected) != 6:
        return False
    scores = list(axis_scores)
    if len(scores) != 6 or {score.key for score in scores} != set(expected):
        return False
    for score in scores:
        proposal = expected[score.key]
        if (score.score != proposal['score'] or
            score.confidence != proposal['confidence'] or
            score.evidence != proposal['evidence'] or
            score.explanation != proposal['explanation'] or
            score.semantic_status != 'unreviewed'):
            return False
    return True


def verify_expected_archives(qa, expected_source, expected_checkpoint):
    """Import may write only archives the operator independently pinned by SHA256.

    Do not infer authenticity merely because checkpoint and source agree.
    """
    for value in (expected_source, expected_checkpoint):
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
            raise CheckpointError('APPLY_REQUIRES_PINNED_SOURCE_AND_CHECKPOINT_SHA256')
    if (expected_source != qa['source_zip_sha256'] or
        expected_checkpoint != qa['checkpoint_zip_sha256']):
        raise CheckpointError('APPLY_ARCHIVE_SHA256_MISMATCH')
    return True
