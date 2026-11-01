"""Offline, read-only company review queue (does not geocode, call APIs or approve data)."""
import csv
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from companies.models import Company
from locations.models import CompanyLocation


class Command(BaseCommand):
    help = 'Export a prioritized queue of source-provisional companies for editor review.'

    def add_arguments(self, parser):
        parser.add_argument('--out', required=True, help='Output CSV path (new file by default).')
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--overwrite', action='store_true')

    def handle(self, *args, **opts):
        if not 1 <= opts['limit'] <= 5000:
            raise CommandError('--limit must be 1..5000')
        dest = Path(opts['out']).resolve()
        if dest.exists() and not opts['overwrite']:
            raise CommandError(f'Output already exists: {dest} (use --overwrite deliberately)')
        qs = Company.objects.filter(Q(identity_status='unverified') | Q(tech_status='unverified') |
                                    Q(tehran_status='unverified')).order_by('-source_work_count',
                                                                                '-source_interview_count', 'id')
        selected = list(qs.select_related('location')[:opts['limit']])
        columns = ['company_id', 'company_name', 'source_url', 'work_experiences', 'interviews',
                   'identity_status', 'tech_status', 'tehran_status', 'location_status',
                   'company_admin_path', 'identity_review_admin_path', 'location_review_admin_path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + '.temporary')
        try:
            with tmp.open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for company in selected:
                    try: loc_status = company.location.verification_status
                    except CompanyLocation.DoesNotExist: loc_status = 'unverified'
                    writer.writerow({
                        'company_id': company.pk,
                        'company_name': company.display_name,
                        'source_url': company.source_url,
                        'work_experiences': company.source_work_count,
                        'interviews': company.source_interview_count,
                        'identity_status': company.identity_status,
                        'tech_status': company.tech_status,
                        'tehran_status': company.tehran_status,
                        'location_status': loc_status,
                        'company_admin_path': f'/admin/companies/company/{company.pk}/change/',
                        'identity_review_admin_path': '/admin/companies/companyverificationevent/add/',
                        'location_review_admin_path': '/admin/locations/companylocationreviewevent/add/',
                    })
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        self.stdout.write(json.dumps({
            'status': 'review_queue_exported', 'selected': len(selected),
            'scope': 'companies with unverified identity, tech or Tehran dimension',
            'external_network_requests': 0, 'database_writes': 0, 'out': str(dest),
        }, ensure_ascii=False))
