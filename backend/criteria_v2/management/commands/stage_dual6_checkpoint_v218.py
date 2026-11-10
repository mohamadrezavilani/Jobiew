"""Private checkpoint import: opt-in, local DEBUG PostgreSQL only, never publish.

Usage: python backend/manage.py stage_dual6_checkpoint_v218 --source ...
       --checkpoint ... --expected-db workplace_insights_dev [--limit 100]

To stage, append --apply --acknowledge-unverified-private-data; takes source
locks and creates new, isolated analysis runs (never overwrites v212 pilots).
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import connection, transaction, DatabaseError

from criteria_v2.checkpoint_contract_v218 import (
    ENGINE, PROMPT, STATUS, CheckpointError,
    load_handoff, select_batch, stage_run_id, summary_only, verify_source_pair,
    stored_scores_match, verify_expected_archives,
)
from criteria_v2.engine_v207 import story_from_experience, validate_response
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore
from criteria_v2.registry import version_for
from experiences.models import PublicExperience


def _guard_local_dev(expected_db):
    cfg = connection.settings_dict
    name = str(cfg.get('NAME') or '')
    host = str(cfg.get('HOST') or '').strip().lower()
    if (os.name != 'nt' or not settings.DEBUG or
        cfg.get('ENGINE') != 'django.db.backends.postgresql' or
        name != expected_db or not name.endswith('_dev') or
        host not in ('', 'localhost', '127.0.0.1', '::1') or
        os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0'):
        raise CommandError('Only local Windows DEBUG PostgreSQL _dev, publication disabled')
    return name


def _reviewed_scores_match(normalized, prior):
    """Accept unchanged human-reviewed runs during cumulative checkpoint reimport.

    Never overwrite human decisions; reject any edited value/evidence or
    unverified stored review receipt.
    """
    dimensions = normalized.get('dimensions')
    rows = list(prior.axis_scores.all())
    if not isinstance(dimensions, dict) or len(rows) != 6 or set(dimensions) != {r.key for r in rows}:
        return False
    for row in rows:
        item = dimensions[row.key]
        status = 'approved' if row.score is not None else 'abstained'
        if (row.score != item['score'] or row.confidence != item['confidence'] or
                row.evidence != item['evidence'] or row.explanation != item['explanation'] or
                row.semantic_status != status):
            return False
    if prior.review_status == 'approved':
        from criteria_v2.checkpoint_receipt_v222 import checkpoint_release_ready
        return checkpoint_release_ready(prior)
    if prior.review_status == 'no_evaluable_scores':
        from criteria_v2.models import CriteriaScoreReviewEvent
        if any(row.score is not None for row in rows):
            return False
        review = CriteriaScoreReviewEvent.objects.filter(analysis=prior).first()
        return (review is not None and
                review.source_content_sha256 == prior.source_content_sha256 and
                review.decisions == {r.key: 'abstain' for r in rows})
    return False


def _existing_run(exp, row, normalized):
    """No competing versions of this checkpoint-engine run for the same source."""
    matches = list(CriteriaAnalysis.objects.filter(
        experience=exp, raw_payload__engine=ENGINE,
    ).prefetch_related('axis_scores'))
    run_id = stage_run_id(row)
    if not matches:
        return 'new', run_id
    if len(matches) != 1 or matches[0].run_id != run_id:
        raise CheckpointError('CONFLICTING_CHECKPOINT_RUN_REQUIRES_MANUAL_REVIEW')
    prior = matches[0]
    if (prior.criteria_version != version_for(exp.source_kind) or
        prior.prompt_version != PROMPT or
        prior.model_name != str(row.get('model_name') or 'chatgpt-private-review')[:120] or
        prior.raw_payload.get('story_sha256') != row['story_sha256'] or
        prior.raw_payload.get('publication') != 'DISABLED' or
        prior.raw_payload.get('source_rights') != 'NOT_ESTABLISHED' or
        prior.raw_payload.get('semantic_accuracy') != 'NOT_ESTABLISHED' or
        prior.source_content_sha256 != exp.content_sha256 or
        not (stored_scores_match(normalized, prior.axis_scores.all())
             if prior.review_status == STATUS else _reviewed_scores_match(normalized, prior))):
        raise CheckpointError('STAGED_RUN_CHANGED_OR_INCOMPLETE_REQUIRES_REVIEW')
    return 'existing', run_id


def check_candidate(row, *, lock=False):
    qs = PublicExperience.objects
    if lock:
        qs = qs.select_for_update()
    exp = qs.filter(pk=row['experience_id']).first()
    if exp is None:
        raise CheckpointError('SOURCE_EXPERIENCE_MISSING')
    story = story_from_experience(exp)
    verify_source_pair(row, exp, story)
    normalized = validate_response({
        'stop_reason': 'end_turn',
        'content': [{'type': 'text', 'text': json.dumps(row['prediction'], ensure_ascii=False)}],
    }, kind=exp.source_kind, story=story)
    if normalized['status'] != 'unreviewed' or normalized['dimensions'] is None:
        raise CheckpointError('CHECKPOINT_KIND_REQUIRES_MANUAL_REVIEW')
    current, run_id = _existing_run(exp, row, normalized)
    return exp, story, normalized, current, run_id


def stage_one(row):
    with transaction.atomic():
        exp, story, normalized, state, run_id = check_candidate(row, lock=True)
        if state == 'existing':
            return False
        payload = {
            'engine': ENGINE, 'story_sha256': row['story_sha256'],
            'source_rights': 'NOT_ESTABLISHED',
            'human_reference': 'NOT_INDEPENDENT',
            'semantic_accuracy': 'NOT_ESTABLISHED',
            'confidence_calibrated': False,
            'review_status': 'unverified_private_proposal',
            'publication': 'DISABLED',
        }
        # A distinct source-bound run; v212 records are never deleted/changed.
        run = CriteriaAnalysis.objects.create(
            experience=exp, criteria_version=version_for(exp.source_kind),
            source_content_sha256=exp.content_sha256,
            model_name=str(row.get('model_name') or 'chatgpt-private-review')[:120],
            prompt_version=PROMPT, run_id=run_id,
            review_status=STATUS, raw_payload=payload,
        )
        for key, item in normalized['dimensions'].items():
            CriteriaAxisScore.objects.create(
                analysis=run, key=key, score=item['score'],
                confidence=item['confidence'], evidence=item['evidence'],
                explanation=item['explanation'], semantic_status='unreviewed',
            )
    return True


class Command(BaseCommand):
    help = 'Validate assistant checkpoint + optional private staging; NO publication or paid AI.'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True)
        parser.add_argument('--checkpoint', required=True)
        parser.add_argument('--expected-db', required=True)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--expected-source-sha256', default='')
        parser.add_argument('--expected-checkpoint-sha256', default='')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--acknowledge-unverified-private-data', action='store_true')

    def handle(self, *args, **opts):
        db = _guard_local_dev(opts['expected_db'])
        if opts['apply'] and not opts['acknowledge_unverified_private_data']:
            raise CommandError('Private staging requires explicit --acknowledge-unverified-private-data')
        if opts['acknowledge_unverified_private_data'] and not opts['apply']:
            raise CommandError('Acknowledgement has no meaning without --apply')
        try:
            rows, ledger, qa = load_handoff(opts['source'], opts['checkpoint'])
            if opts['apply']:
                verify_expected_archives(qa, opts['expected_source_sha256'],
                                         opts['expected_checkpoint_sha256'])
            selected, duplicates = select_batch(rows, ledger,
                after_id=opts['after_id'], limit=opts['limit'])
            # Preflight all candidates before first write; recheck under source row lock.
            states = [check_candidate(row)[3] for row in selected]
        except CheckpointError as exc:
            raise CommandError('CHECKPOINT_STAGE_PREFLIGHT_FAILED: ' + str(exc)) from None
        except (ValueError, TypeError, KeyError, ValidationError, DatabaseError):
            raise CommandError('CHECKPOINT_STAGE_PREFLIGHT_REJECTED_WITHOUT_LOGGING_DATA') from None
        report = summary_only(qa, selected=selected, duplicates=duplicates,
            existing=states.count('existing'), would_insert=states.count('new'))
        report.update({'database': db,
                       'mode': 'PRIVATE_STAGE_UNVERIFIED' if opts['apply'] else 'DRY_RUN_READ_ONLY',
                       'inserted': 0, 'changes': 0,
                       'last_candidate_id': selected[-1]['experience_id'] if selected else opts['after_id']})
        if opts['apply']:
            for row in selected:
                try:
                    report['inserted'] += int(stage_one(row))
                except CheckpointError as exc:
                    raise CommandError('PRIVATE_STAGE_ABORTED_AT_ID_' + str(row['experience_id']) +
                                       ': ' + str(exc) +
                                       '; PREVIOUS_ROWS_COMMITTED=' + str(report['inserted'])) from None
                except (ValueError, TypeError, ValidationError, DatabaseError):
                    raise CommandError('PRIVATE_STAGE_DATABASE_OR_VALIDATION_ERROR_AT_ID_' +
                                       str(row['experience_id']) +
                                       '; PREVIOUS_ROWS_COMMITTED=' + str(report['inserted']) +
                                       '; NO_SOURCE_TEXT_IN_LOG') from None
            report['changes'] = report['inserted']
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        self.stdout.write('NO_APPROVALS; NO_PUBLICATION; NO_AI_REQUESTS')
