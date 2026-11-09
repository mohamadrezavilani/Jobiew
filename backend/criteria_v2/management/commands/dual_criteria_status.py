"""Read-only re-review progress. No scoring, publication, or external requests."""
import json
from django.core.management.base import BaseCommand
from criteria_v2.registry import VERSIONS
from criteria_v2.views import pending_queryset
from experiences.models import PublicExperience
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore


class Command(BaseCommand):
    help = 'Print independent work/interview structural re-review counts; never change data.'

    def handle(self, *args, **options):
        kinds = {}
        for kind, version in VERSIONS.items():
            total = PublicExperience.objects.filter(source_kind=kind).count()
            pending = pending_queryset(kind).count()
            kinds[kind] = {'criteria_version': version, 'total_comments': total,
                           'pending_reclassification': pending,
                           'classification_completed_or_excluded': total - pending,
                           'axes': 6}
        data = {'criteria_framework': 'dual_six_v2', 'score_migration': 'NOT_STARTED',
                'old_scores_used_in_new_framework': False,
                'new_analysis_runs': CriteriaAnalysis.objects.count(),
                'new_axis_scores': CriteriaAxisScore.objects.count(),
                'groups': kinds}
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
