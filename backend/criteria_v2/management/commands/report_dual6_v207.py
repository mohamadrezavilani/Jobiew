"""Read-only progress and quality report for private 6+6 candidate analysis."""
import json
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore
from criteria_v2.registry import VERSIONS


class Command(BaseCommand):
    help = 'Read-only report of unpublished work/interview scoring proposals.'

    def handle(self, *args, **options):
        by_kind = {}
        for kind, version in VERSIONS.items():
            runs = CriteriaAnalysis.objects.filter(criteria_version=version)
            by_kind[kind] = {
                'analyses': runs.count(),
                'statuses': {row['review_status']: row['count'] for row in
                             runs.values('review_status').annotate(count=Count('pk'))},
                'numeric_proposals': CriteriaAxisScore.objects.filter(
                    analysis__criteria_version=version, score__isnull=False).count(),
                'abstentions': CriteriaAxisScore.objects.filter(
                    analysis__criteria_version=version, score__isnull=True).count(),
            }
        self.stdout.write(json.dumps({
            'engine': 'jobiew_dual6_evidence_v207',
            'publication': 'DISABLED',
            'frameworks': by_kind,
        }, ensure_ascii=False, indent=2))
