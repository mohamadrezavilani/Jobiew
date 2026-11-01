"""Read-only private operations summary of five-criterion research imports."""
import json
from django.core.management.base import BaseCommand
from django.db.models import Count
from assessments.models import AiAssessment, AiDimension, FIVE_CRITERIA_VERSION
from assessments.five_criteria_contract import KEYS


class Command(BaseCommand):
    help = 'Report private five-criteria import/validation counts; read only and never publishes.'

    def handle(self, *args, **options):
        assessments = AiAssessment.objects.filter(criteria_version=FIVE_CRITERIA_VERSION)
        dims = AiDimension.objects.filter(assessment__criteria_version=FIVE_CRITERIA_VERSION, key__in=KEYS)
        summary = {
            'status': 'RESEARCH_ONLY_NOT_PUBLIC',
            'criteria_version': FIVE_CRITERIA_VERSION,
            'assessments': assessments.count(),
            'unique_work_experiences': assessments.filter(experience__source_kind='work').values('experience_id').distinct().count(),
            'companies_in_scope': assessments.values('experience__company_id').distinct().count(),
            'dimension_rows': dims.count(),
            'provisional_scores': dims.filter(score__isnull=False).count(),
            'abstentions': dims.filter(score__isnull=True).count(),
            'pending_staff_review_assessments': assessments.filter(independent_review_status='unreviewed').count(),
            'not_public': True,
            'database_writes': 0,
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False))
