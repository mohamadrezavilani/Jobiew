"""Staff-side read-only sufficiency preview with explicit company ID."""
import json
from django.core.management.base import BaseCommand, CommandError
from companies.models import Company
from criteria_v2.sufficiency_v208 import company_public_sufficiency


class Command(BaseCommand):
    help = 'Read-only reviewed-data sufficiency preview for one company; no scores published.'

    def add_arguments(self, parser):
        parser.add_argument('--company', required=True)

    def handle(self, *args, **options):
        company = Company.objects.filter(pk=options['company']).first()
        if company is None:
            raise CommandError('Unknown company ID')
        data = company_public_sufficiency(company)
        self.stdout.write(json.dumps({'company_id': company.pk, 'published': False,
            'scoring_formula': 'PROVISIONAL_EQUAL_WEIGHT_MEAN',
            'work': data['work'], 'interview': data['interview']},
            ensure_ascii=False, indent=2))
