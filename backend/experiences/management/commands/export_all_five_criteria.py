"""One ZIP containing ALL eligible unscored employee-review candidates.

Read-only on the Django database. Deliberately NO record/number/company caps.
The ZIP is split into manageable JSONL files internally; one upload only.
"""
from __future__ import annotations
import json
import os
from collections import Counter
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiAssessment, FIVE_CRITERIA_VERSION
from experiences.models import PublicExperience
from experiences.offline_export_all_core_v9 import BatchArchive, make_private_record


class Command(BaseCommand):
    help = 'Export all eligible unscored work experiences into ONE private ZIP (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True, help='A NEW ZIP file, e.g. reports/five_criteria_ALL_remaining.zip')
        parser.add_argument('--batch-size', type=int, default=100, help='Rows per internal JSONL, 1..500 (default 100)')
        parser.add_argument('--overwrite', action='store_true', help='Intentionally replace an existing local ZIP')

    def handle(self, *args, **options):
        output = Path(options['output']).expanduser().resolve()
        batch_size = options['batch_size']
        if output.suffix.lower() != '.zip':
            raise CommandError('Output must end in .zip')
        if not 1 <= batch_size <= 500:
            raise CommandError('--batch-size must be between 1 and 500')
        if output.exists() and not options['overwrite']:
            raise CommandError(f'File exists, choose another --output (or explicitly --overwrite): {output}')
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name(output.name + '.v9-tmp')
        if temp.exists():
            raise CommandError(f'Temporary output already exists: {temp}')
        excluded = Counter()
        current_ids = set(AiAssessment.objects.filter(
            criteria_version=FIVE_CRITERIA_VERSION
        ).values_list('experience_id', flat=True).distinct())

        # No hard cap on records or on the number of experiences from one company.
        # Chunks bound Python memory usage; one ZIP contains all selected records.
        qs = PublicExperience.objects.filter(source_kind='work').select_related('company').order_by('company_id', 'pk')
        try:
            with ZipFile(temp, 'w', compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
                archive = BatchArchive(z, batch_size=batch_size)
                for obj in qs.iterator(chunk_size=500):
                    if (obj.company_attribution_status == 'rejected' or
                        obj.independence_status == 'duplicate' or
                        obj.copyright_review == 'blocked'):
                        excluded['rejected_duplicate_or_blocked'] += 1
                        continue
                    if obj.pk in current_ids:
                        excluded['already_five_v1'] += 1
                        continue
                    record, masked = make_private_record(obj)
                    archive.append(record, masked)
                manifest = archive.complete(excluded, FIVE_CRITERIA_VERSION)
            if manifest['total_selected'] == 0:
                temp.unlink(missing_ok=True)
                self.stdout.write(json.dumps({
                    'status':'NO_ELIGIBLE_RECORDS',
                    'already_scored_skipped': excluded['already_five_v1'],
                    'database_writes': 0,
                }, ensure_ascii=False))
                return
            # Verify every internal entry and checksum before installing the archive.
            import hashlib
            with ZipFile(temp, 'r') as z:
                bad = z.testzip()
                if bad:
                    raise CommandError(f'Corrupt ZIP entry: {bad}')
                for entry in manifest['files']:
                    if hashlib.sha256(z.read(entry['name'])).hexdigest() != entry['sha256']:
                        raise CommandError('SHA256 verification failed: ' + entry['name'])
            os.replace(temp, output)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        self.stdout.write(json.dumps({
            'status':'EXPORTED_ALL_REMAINING_PRIVATE_RESEARCH_INPUT',
            'output':str(output),
            'selected':manifest['total_selected'],
            'companies':manifest['companies_selected'],
            'internal_batches':len(manifest['files']),
            'already_scored_skipped':excluded['already_five_v1'],
            'other_excluded':excluded['rejected_duplicate_or_blocked'],
            'contact_redacted_records':archive.masked,
            'archive_size_bytes':output.stat().st_size,
            'database_writes':0,
            'paid_api_calls':0,
        }, ensure_ascii=False))
