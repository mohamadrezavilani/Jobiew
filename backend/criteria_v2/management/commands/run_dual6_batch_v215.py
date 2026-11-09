"""Local, rights-gated, bounded and resumable dual-six AI execution.

Default: entirely read-only. Execute: no more than ten paid requests, and
only with explicitly cleared source rights, attribution and classification.
No migration, no publication, no retries; each paid attempt receives a
persisted marker *before* the request. Private source text is never logged.
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.utils import IntegrityError

from criteria_v2.bulk_v215 import (
    BULK_VERSION, MODEL_RE, choose_batch, deterministic_run_id,
    sanitized_failure_code, validate_budget,
)
from criteria_v2.engine_v207 import (
    PROMPT_VERSION, build_request, call_claude, safe_usage,
    story_digest, story_from_experience, validate_response,
)
from criteria_v2.management.commands.plan_dual6_rollout_v214 import (
    audit_queryset, candidate_queryset,
)
from criteria_v2.models import (
    CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent,
)
from criteria_v2.registry import VERSIONS
from criteria_v2.rollout_v214 import decide
from experiences.models import PublicExperience


def _source_decision(exp, story, *, exclude_analysis_id=None):
    """Re-evaluate every gate inside source lock, not only during planning."""
    last = (CriteriaReviewEvent.objects.filter(
        experience_id=exp.pk, source_kind=exp.source_kind,
        criteria_version=VERSIONS.get(exp.source_kind, 'INVALID'),
    ).order_by('-created_at', '-pk')
        .values_list('decision', 'source_content_sha256').first())
    qs = CriteriaAnalysis.objects.filter(
        experience_id=exp.pk, source_content_sha256=exp.content_sha256)
    if exclude_analysis_id is not None:
        qs = qs.exclude(pk=exclude_analysis_id)
    return decide(
        kind=exp.source_kind, copyright_review=exp.copyright_review,
        company_attribution_status=exp.company_attribution_status,
        independence_status=exp.independence_status,
        source_digest=exp.content_sha256, story_length=len(story.strip()),
        classification_decision=last[0] if last else None,
        classification_digest=last[1] if last else None,
        existing_analysis=qs.exists(),
    )


def execute_candidate(experience_id, model, *, inference=None):
    """Single candidate with a durable, source-locked paid-attempt marker.

    Caller must enforce the command-level environment/payment approvals. Tests
    may inject a fake inference callable; no transport is invoked by tests.
    """
    run_call = inference or call_claude
    # Source row lock serializes paid attempts for this source in PostgreSQL.
    with transaction.atomic():
        exp = PublicExperience.objects.select_for_update().get(pk=experience_id)
        story = story_from_experience(exp)
        reason = _source_decision(exp, story)
        if reason != 'ready':
            return {'experience_id': experience_id, 'outcome': 'SKIPPED', 'reason': reason,
                    'paid_attempted': 0}
        run_id = deterministic_run_id(exp.pk, exp.content_sha256, model)
        # Full source digest is immutable for this attempt; body can be edited
        # independently, hence also pin the exact story digest.
        digest = story_digest(story)
        analysis = CriteriaAnalysis.objects.create(
            experience=exp, criteria_version=VERSIONS[exp.source_kind],
            source_content_sha256=exp.content_sha256,
            model_name=model, prompt_version=PROMPT_VERSION,
            run_id=run_id, review_status='running',
            raw_payload={'engine': PROMPT_VERSION, 'bulk_version': BULK_VERSION,
                         'story_sha256': digest, 'publication': 'DISABLED'},
        )
        initial_kind, initial_sha = exp.source_kind, exp.content_sha256
    # Crucial: no network request until the marker is committed.
    try:
        payload = build_request(initial_kind, story, model)
        response = run_call(payload)
        proposal = validate_response(response, kind=initial_kind, story=story)
        usage = safe_usage(response)
        with transaction.atomic():
            current = PublicExperience.objects.select_for_update().get(pk=experience_id)
            current_story = story_from_experience(current)
            reason = _source_decision(current, current_story, exclude_analysis_id=analysis.pk)
            if (current.source_kind != initial_kind or
                    current.content_sha256 != initial_sha or
                    story_digest(current_story) != digest or reason != 'ready'):
                CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
                    review_status='stale', raw_payload={
                        'engine': PROMPT_VERSION, 'bulk_version': BULK_VERSION,
                        'story_sha256': digest, 'error_code': 'SOURCE_OR_GATE_CHANGED',
                        'publication': 'DISABLED', 'usage': usage})
                return {'experience_id': experience_id, 'outcome': 'STALE',
                        'reason': 'SOURCE_OR_GATE_CHANGED', 'paid_attempted': 1}
            if proposal['dimensions'] is not None:
                for key, item in proposal['dimensions'].items():
                    CriteriaAxisScore.objects.create(
                        analysis=analysis, key=key, score=item['score'],
                        confidence=item['confidence'], evidence=item['evidence'],
                        explanation=item['explanation'], semantic_status='unreviewed',
                    )
            CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
                review_status=proposal['status'], raw_payload={
                    'engine': PROMPT_VERSION, 'bulk_version': BULK_VERSION,
                    'story_sha256': digest, 'publication': 'DISABLED',
                    'detected_kind': proposal['detected_kind'],
                    'kind_confidence': proposal['kind_confidence'], 'usage': usage,
                })
        return {'experience_id': experience_id, 'outcome': 'SAVED',
                'review_status': proposal['status'], 'paid_attempted': 1}
    except Exception as exc:
        error_code = sanitized_failure_code(exc)
        # Keep failed attempts for no-retry/idempotency. No raw source strings.
        CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
            review_status='failed', raw_payload={
                'engine': PROMPT_VERSION, 'bulk_version': BULK_VERSION,
                'story_sha256': digest, 'error_code': error_code,
                'publication': 'DISABLED',
            })
        return {'experience_id': experience_id, 'outcome': 'FAILED',
                'reason': error_code, 'paid_attempted': 1}


class Command(BaseCommand):
    help = 'Default dry-run; bounded consent-gated private batch. No publication or automatic retries.'

    def add_arguments(self, parser):
        parser.add_argument('--expected-db', required=True)
        parser.add_argument('--limit', type=int, default=5)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--kind', choices=['work', 'interview'])
        parser.add_argument('--model', default='')
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--approve-paid-api', action='store_true')

    def handle(self, *args, **opts):
        try:
            validate_budget(opts['limit'], opts['after_id'])
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        if os.name != 'nt' or not settings.DEBUG:
            raise CommandError('Windows development only; production disabled')
        cfg = connection.settings_dict
        hostname = str(cfg.get('HOST') or '').lower().strip()
        db_name = str(cfg.get('NAME') or '')
        if (cfg.get('ENGINE') != 'django.db.backends.postgresql'
                or hostname not in ('', 'localhost', '127.0.0.1', '::1')
                or db_name != opts['expected_db'] or not db_name.endswith('_dev')):
            raise CommandError('Local PostgreSQL _dev database and exact --expected-db required')
        if os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0':
            raise CommandError('Publication must remain disabled')

        execute = opts['execute']
        model = opts['model'] or os.environ.get('JOBIEW_DUAL6_MODEL', '')
        if execute:
            if (not opts['approve_paid_api'] or
                os.environ.get('JOBIEW_DUAL6_PAID_ENABLED') != '1' or
                os.environ.get('JOBIEW_DUAL6_EXTERNAL_TEXT_APPROVED') != '1' or
                not os.environ.get('ANTHROPIC_API_KEY', '').strip() or
                not MODEL_RE.fullmatch(model)):
                raise CommandError('Paid mode requires all explicit approvals, API key, and valid --model')

        # Reusing the v214 source gates means no accidental skip of copyright,
        # company attribution, source-type review, old runs or malformed text.
        records = audit_queryset(candidate_queryset(after_id=opts['after_id'],kind=opts['kind']))
        plan = choose_batch(records, limit=opts['limit'], after_id=opts['after_id'])
        attempts = []
        if execute:
            # Unchanged source, rights and last review are rechecked under lock.
            for item in plan['selected']:
                attempts.append(execute_candidate(item['experience_id'],model))

        result = {
            'mode': 'EXECUTE_BOUNDED_PRIVATE' if execute else 'DRY_RUN_READ_ONLY',
            'database': db_name,
            'scanned': plan['scanned'],
            'next_batch_size': plan['selected_count'],
            'next_batch': plan['selected'] if not execute else [],
            'last_scanned_id': plan['last_scanned_id'],
            'blockers_in_scan': plan['blockers_in_scan'],
            'paid_request_ceiling': opts['limit'] if execute else 0,
            'paid_attempted': sum(x.get('paid_attempted', 0) for x in attempts),
            'outcomes': {'saved':sum(x['outcome']=='SAVED' for x in attempts),
                         'failed':sum(x['outcome']=='FAILED' for x in attempts),
                         'stale':sum(x['outcome']=='STALE' for x in attempts),
                         'skipped':sum(x['outcome']=='SKIPPED' for x in attempts)},
            'human_approval': 'NONE', 'publication': 'DISABLED',
            'auto_retry': False,
        }
        self.stdout.write(json.dumps(result,ensure_ascii=False,sort_keys=True))
        self.stdout.write('PUBLICATION: DISABLED; HUMAN_APPROVAL: NONE')
