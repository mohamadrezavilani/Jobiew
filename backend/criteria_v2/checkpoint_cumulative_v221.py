"""Validate cumulative GPT-6 checkpoint ZIPs without executing archived notes.

For private staging only. All file hashes and identities are verified. Source
content and evidence must ALSO match the local PostgreSQL row in the importer;
this offline loader cannot independently establish rights or semantic truth.
"""
from collections import Counter
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
import zipfile

from .checkpoint_qav218 import AXES, STATES, CheckpointError, strict_json, parse_jsonl

MAX_ZIP_SIZE = 120 * 1024 * 1024
MAX_UNCOMPRESSED = 240 * 1024 * 1024
MAX_FILES = 500
HEX_SHA = re.compile(r'[a-f0-9]{64}\Z')
REVIEWED_STATES = {'assistant_reviewed_draft', 'assistant_reviewed_all_null'}


def require(test, label):
    if not test:
        raise CheckpointError(label)


def hexdigest(raw):
    return sha256(raw).hexdigest()


def check_sha(value):
    return type(value) is str and HEX_SHA.fullmatch(value) is not None


def validate_cumulative(checkpoint_path, *, expected_checkpoint_sha256,
                        expected_source_sha256):
    """Read-only. Returns (predictions, ledger map, safe QA summary).

    SHA pins must be supplied independently by the operator. The original
    exported source ZIP is optional only because the database import phase
    verifies each candidate's company, kind, content hash, story hash, and
    literal evidence against an independently existing source DB row.
    """
    require(check_sha(expected_checkpoint_sha256) and check_sha(expected_source_sha256),
            'PINNED_SOURCE_AND_CHECKPOINT_SHA256_REQUIRED')
    path = Path(checkpoint_path)
    require(path.is_file() and path.stat().st_size <= MAX_ZIP_SIZE,
            'CHECKPOINT_NOT_FOUND_OR_OVERSIZE')
    require(hexdigest(path.read_bytes()) == expected_checkpoint_sha256,
            'CHECKPOINT_ARCHIVE_SHA256_MISMATCH')
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [x.filename for x in infos]
            require(len(infos) <= MAX_FILES and len(names) == len(set(names))
                    and sum(x.file_size for x in infos) <= MAX_UNCOMPRESSED
                    and all(x.file_size <= MAX_ZIP_SIZE for x in infos),
                    'CHECKPOINT_ZIP_SIZE_OR_DUPLICATE_MEMBER')
            for info in infos:
                name = info.filename
                p = PurePosixPath(name)
                require(name and not p.is_absolute() and '..' not in p.parts
                        and '\\' not in name and not name.endswith('/')
                        and ((info.external_attr >> 16) & 0o170000) != 0o120000,
                        'UNSAFE_ARCHIVE_MEMBER')
            require(z.testzip() is None, 'CHECKPOINT_CRC_FAILED')
            required = {'files_sha256.json', 'checkpoint.json', 'quality_audit.json',
                        'assistant_predictions.jsonl', 'ledger.jsonl'}
            require(required.issubset(set(names)), 'CHECKPOINT_REQUIRED_MEMBERS_MISSING')
            hashes = strict_json(z.read('files_sha256.json'))
            require(type(hashes) is dict and set(hashes) == set(names) - {'files_sha256.json'},
                    'CHECKPOINT_MANIFEST_INCOMPLETE_OR_EXTRANEOUS')
            for name, expected in hashes.items():
                require(check_sha(expected) and hexdigest(z.read(name)) == expected,
                        'CHECKPOINT_INTERNAL_MEMBER_SHA256_MISMATCH')
            checkpoint = strict_json(z.read('checkpoint.json'))
            quality = strict_json(z.read('quality_audit.json'))
            ledger = parse_jsonl(z.read('ledger.jsonl'), 'ledger')
            predictions = parse_jsonl(z.read('assistant_predictions.jsonl'), 'predictions')
    except (zipfile.BadZipFile, OSError, UnicodeError, KeyError, TypeError) as exc:
        raise CheckpointError('UNREADABLE_PRIVATE_CHECKPOINT_' + type(exc).__name__) from None
    require(checkpoint.get('source_archive_sha256') == expected_source_sha256,
            'CHECKPOINT_SOURCE_PIN_MISMATCH')
    require(checkpoint.get('source_rights') == 'NOT_ESTABLISHED'
            and checkpoint.get('company_attribution') == 'UNVERIFIED'
            and checkpoint.get('publication') == 'DISABLED'
            and checkpoint.get('independent_semantic_accuracy_established') is False
            and checkpoint.get('no_independent_human_gold') is True,
            'PUBLICATION_OR_RIGHTS_FLAGS_NOT_UNVERIFIED')
    require(quality.get('validation') == 'PASS'
            and quality.get('validation_scope') == 'structural_schema_and_verbatim_evidence_only'
            and quality.get('semantic_claims_fact_checked') is False
            and quality.get('publication_enabled') is False,
            'INVALID_QUALITY_AUDIT_SCOPE')
    total = checkpoint.get('source_records_verified')
    require(type(total) is int and 1 <= total <= 100_000 and len(ledger) == total,
            'CHECKPOINT_SOURCE_LEDGER_COUNT_MISMATCH')
    require([row.get('experience_id') for row in ledger] == list(range(1, total + 1)),
            'CHECKPOINT_LEDGER_NONCONTIGUOUS_OR_DUPLICATE')
    ledger_map = {row['experience_id']: row for row in ledger}
    states = Counter()
    source_kinds = Counter()
    duplicate_count = 0
    for row in ledger:
        i = row['experience_id']
        kind = row.get('kind')
        require(kind in AXES and row.get('status') in STATES
                and check_sha(row.get('source_content_sha256'))
                and check_sha(row.get('story_sha256'))
                and type(row.get('company_id')) is str and bool(row['company_id'])
                and type(row.get('story_length')) is int and row['story_length'] >= 0,
                'CHECKPOINT_LEDGER_ROW_INVALID')
        states[row['status']] += 1
        source_kinds[kind] += 1
        prior = row.get('exact_duplicate_of_experience_id')
        if prior is not None:
            duplicate_count += 1
            require(type(prior) is int and 0 < prior < i
                    and ledger_map[prior]['story_sha256'] == row['story_sha256'],
                    'CHECKPOINT_UNPROVEN_EXACT_DUPLICATE')
    require(dict(states) == checkpoint.get('status_counts')
            and dict(source_kinds) == checkpoint.get('source_kind_counts')
            and duplicate_count == checkpoint.get('exact_duplicate_stories'),
            'CHECKPOINT_LEDGER_SUMMARY_MISMATCH')
    reviewed = states['assistant_reviewed_draft'] + states['assistant_reviewed_all_null']
    require(reviewed == len(predictions) == checkpoint.get('assistant_reviewed_records')
            and reviewed == quality.get('reviewed_record_count'),
            'CHECKPOINT_REVIEWED_TOTAL_MISMATCH')
    seen = set()
    counts = Counter()
    kinds_reviewed = Counter()
    for row in predictions:
        i = row.get('experience_id')
        require(type(i) is int and i in ledger_map and i not in seen,
                'CHECKPOINT_PREDICTION_ID_INVALID_OR_DUPLICATE')
        seen.add(i)
        source = ledger_map[i]
        kind = source['kind']
        require(row.get('kind') == kind
                and row.get('company_id') == source['company_id']
                and row.get('source_content_sha256') == source['source_content_sha256']
                and row.get('story_sha256') == source['story_sha256']
                and row.get('state') == source['status']
                and row.get('state') in REVIEWED_STATES
                and row.get('review_status') == 'unverified_private_proposal',
                'CHECKPOINT_PREDICTION_SOURCE_IDENTITY_MISMATCH')
        pred = row.get('prediction')
        require(type(pred) is dict and set(pred) == {'detected_kind', 'kind_confidence', 'dimensions'}
                and pred['detected_kind'] == kind
                and type(pred['kind_confidence']) is int and 70 <= pred['kind_confidence'] <= 100,
                'CHECKPOINT_PREDICTION_KIND_INVALID')
        dimensions = pred['dimensions']
        require(type(dimensions) is dict and set(dimensions) == set(AXES[kind]),
                'CHECKPOINT_PREDICTION_AXES_INVALID')
        numeric = 0
        for axis, dim in dimensions.items():
            require(type(dim) is dict and set(dim) == {'score', 'confidence', 'evidence', 'explanation'},
                    'CHECKPOINT_DIMENSION_FIELDS_INVALID')
            score, confidence, evidence, explanation = (dim[k] for k in
                    ('score', 'confidence', 'evidence', 'explanation'))
            require(type(confidence) is int and type(evidence) is str
                    and type(explanation) is str and 8 <= len(explanation.strip()) <= 600,
                    'CHECKPOINT_DIMENSION_TYPES_INVALID')
            if score is None:
                require(confidence == 0 and evidence == '', 'CHECKPOINT_NULL_DIMENSION_INVALID')
                counts['abstentions'] += 1
            else:
                require(type(score) is int and 1 <= score <= 10
                        and 70 <= confidence <= 100 and 12 <= len(evidence) <= 450
                        and not any(p in evidence for p in ('[email]', '[phone]', '[number]')),
                        'CHECKPOINT_NUMERIC_DIMENSION_INVALID')
                numeric += 1
                counts['numeric_proposals'] += 1
        require((numeric == 0) == (row['state'] == 'assistant_reviewed_all_null'),
                'CHECKPOINT_ALL_NULL_CLASSIFICATION_MISMATCH')
        kinds_reviewed[kind] += 1
    require(seen == {i for i, row in ledger_map.items() if row['status'] in REVIEWED_STATES},
            'CHECKPOINT_MISSING_REVIEWED_PROPOSAL')
    require(counts['numeric_proposals'] == checkpoint.get('assistant_numeric_axis_proposals')
            == quality.get('numeric_axis_count')
            and counts['abstentions'] == checkpoint.get('assistant_null_axis_proposals')
            == quality.get('abstained_axis_count'),
            'CHECKPOINT_AXIS_COUNTS_MISMATCH')
    for kind, n in kinds_reviewed.items():
        require(n == quality['by_kind'][kind]['reviewed'], 'CHECKPOINT_KIND_COUNT_MISMATCH')
    safe_summary = {
        'source_records': total, 'reviewed': reviewed,
        'numeric_proposals': counts['numeric_proposals'],
        'abstentions': counts['abstentions'],
        'exact_source_duplicates': duplicate_count,
        'source_zip_sha256': expected_source_sha256,
        'checkpoint_zip_sha256': expected_checkpoint_sha256,
        'publication': 'DISABLED', 'independent_quality': 'NOT_ESTABLISHED',
        'source_archive_verified_here': False,
        'candidate_source_db_verification_required': True,
        'unexecuted_archive_members_checked': len(hashes),
    }
    return sorted(predictions, key=lambda row: row['experience_id']), ledger_map, safe_summary