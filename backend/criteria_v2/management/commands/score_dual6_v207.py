"""Guarded staff-only offline CLI for pilot six-axis AI proposals.

Usage preview: python manage.py score_dual6_v207 --limit 5
Actual paid API calls require --execute --approve-paid-api plus two env flags.
Nothing in this command publishes scores, changes experiences, or edits old AI.
"""
import hashlib
import json
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from criteria_v2.engine_v207 import (
    PROMPT_VERSION, ProposalError, build_request, call_claude,
    safe_usage, story_digest, story_from_experience, validate_response,
)
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent
from criteria_v2.registry import VERSIONS
from experiences.models import PublicExperience


class Command(BaseCommand):
    help = 'Safely preview or explicitly run paid 6+6 proposals. Never publishes any rating.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=5, help='1..20 per run, default 5')
        parser.add_argument('--kind', choices=['work', 'interview'], default=None)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--model', type=str, default='')
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--approve-paid-api', action='store_true')

    def handle(self, *args, **options):
        limit = options['limit']
        if not 1 <= limit <= 20 or options['after_id'] < 0:
            raise CommandError('--limit must be 1..20 and --after-id nonnegative')
        execute = options['execute']
        model = options['model'] or os.environ.get('JOBIEW_DUAL6_MODEL', '')
        if execute:
            if not options['approve_paid_api']:
                raise CommandError('Paid execution needs explicit --approve-paid-api')
            if os.environ.get('JOBIEW_DUAL6_PAID_ENABLED') != '1':
                raise CommandError('JOBIEW_DUAL6_PAID_ENABLED must be 1')
            if os.environ.get('JOBIEW_DUAL6_EXTERNAL_TEXT_APPROVED') != '1':
                raise CommandError('Third-party text processing approval is required')
            if not os.environ.get('ANTHROPIC_API_KEY', '').strip():
                raise CommandError('ANTHROPIC_API_KEY_MISSING')
            if not re.fullmatch(r'claude-[a-z0-9-]{4,90}', model):
                raise CommandError('Set valid --model or JOBIEW_DUAL6_MODEL')
        else:
            model = model or 'unset-model-preview'

        qs = PublicExperience.objects.order_by('pk').filter(pk__gt=options['after_id'])
        if options['kind']:
            qs = qs.filter(source_kind=options['kind'])

        # Scan can skip ineligible/previously evaluated sources. Limit bounds payable calls.
        summary = dict(mode='EXECUTE' if execute else 'PREVIEW', inspected=0,
                       eligible=0, paid_attempts=0, saved=0,
                       needs_review=0, skipped=0, failed=0, last_id=options['after_id'])
        for exp in qs.iterator(chunk_size=100):
            summary['inspected'] += 1
            summary['last_id'] = exp.pk
            if exp.source_kind not in VERSIONS:
                summary['skipped'] += 1
                continue
            if (exp.copyright_review == 'blocked' or
                exp.company_attribution_status == 'rejected' or
                exp.independence_status == 'duplicate'):
                summary['skipped'] += 1
                continue
            if not re.fullmatch(r'[a-fA-F0-9]{64}', exp.content_sha256 or ''):
                summary['skipped'] += 1
                continue
            story = story_from_experience(exp)
            if len(story.strip()) < 50:
                summary['skipped'] += 1
                continue
            last_decision = (CriteriaReviewEvent.objects.filter(
                experience_id=exp.pk, criteria_version=VERSIONS[exp.source_kind],
                source_kind=exp.source_kind, source_content_sha256=exp.content_sha256,
            ).order_by('-created_at', '-pk').values_list('decision', flat=True).first())
            if last_decision in ('excluded', 'needs_revision'):
                summary['skipped'] += 1
                continue
            rid = 'dual6v207_' + hashlib.sha256(
                f'{exp.pk}|{exp.content_sha256}|{model}|{PROMPT_VERSION}'.encode('utf-8')
            ).hexdigest()
            if execute and CriteriaAnalysis.objects.filter(run_id=rid).exists():
                summary['skipped'] += 1
                continue
            summary['eligible'] += 1
            if not execute:
                self.stdout.write(f'PREVIEW experience_id={exp.pk} kind={exp.source_kind} chars={len(story)}')
                if summary['eligible'] >= limit:
                    break
                continue
            # This audit marker is written BEFORE external request, preventing accidental paid retries.
            with transaction.atomic():
                fresh = PublicExperience.objects.select_for_update().get(pk=exp.pk)
                if (fresh.content_sha256 != exp.content_sha256 or
                    fresh.source_kind != exp.source_kind or
                    fresh.copyright_review == 'blocked' or
                    fresh.company_attribution_status == 'rejected' or
                    fresh.independence_status == 'duplicate'):
                    summary['skipped'] += 1
                    continue
                if CriteriaAnalysis.objects.filter(run_id=rid).exists():
                    summary['skipped'] += 1
                    continue
                analysis = CriteriaAnalysis.objects.create(
                    experience=fresh, criteria_version=VERSIONS[fresh.source_kind],
                    source_content_sha256=fresh.content_sha256, model_name=model,
                    prompt_version=PROMPT_VERSION, run_id=rid,
                    review_status='running', raw_payload={
                        'engine': PROMPT_VERSION, 'story_sha256': story_digest(story),
                    },
                )
            summary['paid_attempts'] += 1
            try:
                # No retries. A failed run remains recorded so it cannot silently incur more charges.
                response = call_claude(build_request(exp.source_kind, story, model))
                proposal = validate_response(response, kind=exp.source_kind, story=story)
                usage = safe_usage(response)
                with transaction.atomic():
                    current = PublicExperience.objects.select_for_update().get(pk=exp.pk)
                    latest_review = (CriteriaReviewEvent.objects.filter(
                        experience_id=current.pk, criteria_version=VERSIONS[exp.source_kind],
                        source_kind=exp.source_kind, source_content_sha256=exp.content_sha256
                    ).order_by('-created_at', '-pk').values_list('decision', flat=True).first())
                    if (current.source_kind != exp.source_kind or
                        current.content_sha256 != exp.content_sha256 or
                        current.copyright_review == 'blocked' or
                        current.company_attribution_status == 'rejected' or
                        current.independence_status == 'duplicate' or
                        latest_review in ('excluded', 'needs_revision')):
                        CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
                            review_status='stale', raw_payload={
                                'engine': PROMPT_VERSION, 'story_sha256': story_digest(story),
                                'usage': usage, 'error_code': 'SOURCE_CHANGED_DURING_CALL'})
                        summary['failed'] += 1
                        self.stdout.write(f'STALE experience_id={exp.pk}')
                        continue
                    if proposal['dimensions'] is not None:
                        for key, item in proposal['dimensions'].items():
                            CriteriaAxisScore.objects.create(
                                analysis=analysis, key=key, score=item['score'],
                                confidence=item['confidence'], evidence=item['evidence'],
                                explanation=item['explanation'], semantic_status='unreviewed',
                            )
                    CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
                        review_status=proposal['status'], raw_payload={
                            'engine': PROMPT_VERSION, 'story_sha256': story_digest(story),
                            'detected_kind': proposal['detected_kind'],
                            'kind_confidence': proposal['kind_confidence'],
                            'usage': usage,
                        })
                summary['saved'] += 1
                if proposal['status'] == 'needs_review':
                    summary['needs_review'] += 1
                self.stdout.write(f'SAVED experience_id={exp.pk} status={proposal["status"]}')
            except Exception as exc:
                # Only error class/code is stored; never log raw story/response/credentials.
                code = str(exc) if isinstance(exc, ProposalError) else (
                    str(exc) if isinstance(exc, RuntimeError) and
                    str(exc).startswith(('ANTHROPIC_', 'MODEL_RESPONSE_')) else type(exc).__name__)
                CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
                    review_status='failed', raw_payload={
                        'engine': PROMPT_VERSION, 'story_sha256': story_digest(story),
                        'error_code': code[:120],
                    })
                summary['failed'] += 1
                self.stdout.write(f'FAILED experience_id={exp.pk} code={code[:120]}')
            if summary['paid_attempts'] >= limit:
                break
        self.stdout.write(json.dumps(summary, ensure_ascii=False))
        self.stdout.write('PUBLICATION: DISABLED')
