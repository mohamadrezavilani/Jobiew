"""Offline, read-only progress checks that avoid printing private experience bodies."""
import json
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from companies.models import Company
from experiences.models import PublicExperience
from assessments.models import AiAssessment, AiDimension, RatingSnapshot
from locations.models import CompanyLocation
from voting.models import ActiveVote


class Command(BaseCommand):
    help = 'Print source coverage, review backlog and no-publication counters as JSON.'

    def handle(self, *args, **options):
        complete_company = Company.objects.filter(
            identity_status='verified', tech_status='verified', tehran_status='verified'
        ).count()
        verified_map = CompanyLocation.objects.filter(
            verification_status='verified',
            company__identity_status='verified', company__tehran_status='verified',
            latitude__isnull=False, longitude__isnull=False,
        ).exclude(evidence_url='').count()
        counts = {
            'companies': Company.objects.count(),
            'company_identity_verified': Company.objects.filter(identity_status='verified').count(),
            'company_tech_verified': Company.objects.filter(tech_status='verified').count(),
            'company_tehran_verified': Company.objects.filter(tehran_status='verified').count(),
            'companies_three_checks_verified': complete_company,
            'public_experiences': PublicExperience.objects.count(),
            'work_experiences': PublicExperience.objects.filter(source_kind='work').count(),
            'interviews': PublicExperience.objects.filter(source_kind='interview').count(),
            'experiences_attribution_verified': PublicExperience.objects.filter(company_attribution_status='verified').count(),
            'experiences_copyright_approved': PublicExperience.objects.filter(copyright_review='approved').count(),
            'experiences_publicly_visible': PublicExperience.objects.filter(published_publicly=True).count(),
            'historical_ai_assessments': AiAssessment.objects.count(),
            'ai_dimension_rows': AiDimension.objects.count(),
            'ai_assessments_independently_reviewed': AiAssessment.objects.filter(independent_review_status='approved').count(),
            'ai_assessments_publish_approved': AiAssessment.objects.filter(publish_approved=True).count(),
            'rating_snapshots_publish_approved': RatingSnapshot.objects.filter(publish_approved=True).count(),
            'verified_map_points': verified_map,
            'active_user_votes': ActiveVote.objects.count(),
            'claude_network_requests': 0,
        }
        self.stdout.write(json.dumps({'read_only': True, 'counts': counts}, ensure_ascii=False))
