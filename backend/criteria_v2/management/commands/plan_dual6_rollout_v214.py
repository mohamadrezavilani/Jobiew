"""Read-only audit and bounded next-batch preview for independent 6+6 scoring.

The command CANNOT score, approve, publish, migrate, or call external APIs.
Windows-local DEBUG PostgreSQL only. Every source must be independently
cleared before appearing in a candidate batch; no silent approval bypass.
"""
import json
import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Case, CharField, Exists, OuterRef, Subquery, Value, When

from criteria_v2.engine_v207 import story_from_experience
from criteria_v2.models import CriteriaAnalysis, CriteriaReviewEvent
from criteria_v2.registry import VERSIONS
from criteria_v2.rollout_v214 import decide, summarize
from experiences.models import PublicExperience


class Command(BaseCommand):
    help = 'Read-only per-reason 6+6 rollout audit and eligible next-batch preview; NO AI calls.'

    def add_arguments(self, parser):
        parser.add_argument('--expected-db', required=True)
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--kind', choices=['work','interview'], default=None)

    def handle(self, *args, **opts):
        if os.name != 'nt' or not settings.DEBUG:
            raise CommandError('Windows local development only; production refused')
        cfg = connection.settings_dict
        host = str(cfg.get('HOST') or '').strip().lower()
        db_name = str(cfg.get('NAME') or '')
        if (cfg.get('ENGINE') != 'django.db.backends.postgresql' or
            host not in ('', 'localhost','127.0.0.1','::1') or
            not db_name.endswith('_dev') or db_name != opts['expected_db']):
            raise CommandError('Explicitly named local PostgreSQL _dev database required')
        if os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED','0') != '0':
            raise CommandError('Publication flag must be disabled')
        if opts['limit'] < 1 or opts['limit'] > 100 or opts['after_id'] < 0:
            raise CommandError('limit=1..100, after-id>=0')

        # Latest event across *all* hashes wins: stale confirmations are invalid.
        qs = candidate_queryset(after_id=opts['after_id'], kind=opts['kind'])
        records = audit_queryset(qs)
        summary=summarize(records,cap=opts['limit'],after_id=opts['after_id'])
        summary['database']=db_name
        summary['kind_filter']=opts['kind'] or 'all'
        summary['mode']='READ_ONLY_ELIGIBILITY_AUDIT'
        self.stdout.write(json.dumps(summary,ensure_ascii=False,sort_keys=True))
        self.stdout.write('NO_SCORE_WRITES; NO_APPROVALS; NO_AI_REQUESTS; NO_PUBLICATION')


def audit_queryset(qs):
    """ORM-free iteration wrapper for isolated DB integration tests."""
    records = []
    for exp in qs.iterator(chunk_size=250):
        n = -1
        if (exp.copyright_review == 'approved' and
            exp.company_attribution_status == 'verified' and
            exp.independence_status != 'duplicate'):
            n = len(story_from_experience(exp).strip())
        reason = decide(
            kind=exp.source_kind, copyright_review=exp.copyright_review,
            company_attribution_status=exp.company_attribution_status,
            independence_status=exp.independence_status,
            source_digest=exp.content_sha256, story_length=n,
            classification_decision=exp.last_decision,
            classification_digest=exp.last_review_digest,
            existing_analysis=exp.already_analyzed)
        records.append((exp.pk, exp.source_kind, reason))
    return records


def candidate_queryset(*, after_id=0, kind=None):
    """Portable, newest-first per-experience review and current-source run lock."""
    latest_classification = CriteriaReviewEvent.objects.filter(
        experience_id=OuterRef('pk'),
        source_kind=OuterRef('source_kind'),
        criteria_version=Case(
            When(source_kind='work', then=Value(VERSIONS['work'])),
            default=Value(VERSIONS['interview']), output_field=CharField(),
        ),
    ).order_by('-created_at', '-pk')
    current_analysis = CriteriaAnalysis.objects.filter(
        experience_id=OuterRef('pk'),
        source_content_sha256=OuterRef('content_sha256'),
    )
    qs = (PublicExperience.objects.filter(pk__gt=after_id)
          .filter(source_kind__in=('work', 'interview'))
          .annotate(
              last_decision=Subquery(latest_classification.values('decision')[:1]),
              last_review_digest=Subquery(latest_classification.values('source_content_sha256')[:1]),
              already_analyzed=Exists(current_analysis))
          .order_by('pk'))
    if kind:
        qs = qs.filter(source_kind=kind)
    return qs
