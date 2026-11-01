"""Read-only Django/PostgreSQL -> portable JSONL/ZIP review packets for ChatGPT.

The command NEVER writes database state. It excludes existing five_v1 assessments;
import the evaluated output with `import_five_criteria_ai` (dry run first).
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiAssessment, FIVE_CRITERIA_VERSION
from experiences.models import PublicExperience
from experiences.offline_export_core_v8 import redact_contacts, choose_company_bundles


class Command(BaseCommand):
    help = 'Export PRIVATE, uns cored work narratives in small ZIP batches; no DB writes or paid API.'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True, help='Destination ZIP, e.g. reports/five_criteria_batch_01.zip')
        parser.add_argument('--max-records', type=int, default=75)
        parser.add_argument('--batch-size', type=int, default=25)
        parser.add_argument('--min-company-reviews', type=int, default=3)
        parser.add_argument('--max-per-company', type=int, default=5)
        parser.add_argument('--overwrite', action='store_true', help='Replace an existing ZIP intentionally')

    def handle(self, *args, **options):
        max_records = options['max_records']
        batch_size = options['batch_size']
        minimum_company_reviews = options['min_company_reviews']
        max_per_company = options['max_per_company']
        if not (1 <= max_records <= 500 and 1 <= batch_size <= 100 and
                1 <= minimum_company_reviews <= 100 and 1 <= max_per_company <= 100):
            raise CommandError('Limits out of range: max-records 1..500, batch-size 1..100, min-company-reviews 1..100, max-per-company 1..100')
        out = Path(options['output']).expanduser().resolve()
        if out.suffix.lower() != '.zip':
            raise CommandError('--output must be .zip')
        if out.exists() and not options['overwrite']:
            raise CommandError(f'Output already exists: {out}; use a new filename or --overwrite')
        out.parent.mkdir(parents=True, exist_ok=True)

        # A single FK per experience can have multiple attempts. Do not re-export
        # a source with ANY previously imported five_v1 run, regardless of dataset-id.
        existing_qs = AiAssessment.objects.filter(criteria_version=FIVE_CRITERIA_VERSION).values_list('experience_id', flat=True).distinct()
        already_ids = set(existing_qs)
        grouped = defaultdict(list)
        already_by_company = defaultdict(int)
        excluded = defaultdict(int)
        all_work = PublicExperience.objects.filter(source_kind='work').select_related('company').order_by('company_id', 'pk')
        for obj in all_work.iterator(chunk_size=500):
            if obj.company_attribution_status == 'rejected' or obj.independence_status == 'duplicate' or obj.copyright_review == 'blocked':
                excluded['rejected_duplicate_or_blocked'] += 1
                continue
            if obj.pk in already_ids:
                already_by_company[obj.company_id] += 1
                excluded['already_five_v1'] += 1
                continue
            grouped[obj.company_id].append({'pk':obj.pk, 'source_url':obj.source_url, 'obj':obj})

        chosen = choose_company_bundles(grouped, limit=max_records,
                                       minimum_company_reviews=minimum_company_reviews,
                                       max_per_company=max_per_company,
                                       already_count=already_by_company)
        batches = []
        tally = defaultdict(int)
        for offset in range(0, len(chosen), batch_size):
            records = []
            for item in chosen[offset:offset + batch_size]:
                obj = item['obj']
                body, mbody = redact_contacts(obj.body)
                title, mtitle = redact_contacts(obj.title)
                job_title, mjob = redact_contacts(obj.job_title)
                pros = []
                cons = []
                masked = mbody or mtitle or mjob
                for orig, target in ((obj.pros, pros), (obj.cons, cons)):
                    for v in orig if isinstance(orig, list) else []:
                        cleaned, did = redact_contacts(str(v))
                        target.append(cleaned)
                        masked = masked or did
                if masked:
                    tally['contact_redactions'] += 1
                record = {
                    'review_id': f'PG_{obj.pk}',
                    'source': 'workplace_insights_postgresql_read_only',
                    'source_url': obj.source_url,
                    'source_content_sha256': obj.content_sha256,
                    'company_id': str(obj.company_id),
                    'company': obj.company.display_name,
                    'title': title,
                    'job_title': job_title,
                    'published_jalali': obj.published_jalali,
                    'employment_period_jalali': obj.employment_period_jalali,
                    'review_type': obj.source_kind,
                    'body': body,
                    'pros': pros,
                    'cons': cons,
                    'copyright_review': obj.copyright_review,
                    'company_attribution_status': obj.company_attribution_status,
                    'independence_status': obj.independence_status,
                    'privacy_contact_masked': masked,
                    'record_type_warning': 'source_kind=work alone does not establish employee experience',
                    'assessment_status': 'NOT_SCORED_USE_ONLY_AS_PRIVATE_RESEARCH_INPUT',
                }
                records.append(record)
            batches.append(records)

        manifest = {
            'format': 'workplace_five_v1_offline_input_v8',
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'source': 'PostgreSQL/Django/PublicExperience',
            'criteria_version': FIVE_CRITERIA_VERSION,
            'research_only_not_public': True,
            'database_writes': 0,
            'paid_api_calls': 0,
            'total_selected':len(chosen),
            'batch_size':batch_size,
            'files': [],
            'companies_selected':len({item['obj'].company_id for item in chosen}),
            'excluded':dict(excluded),
            'contact_redacted_records':tally['contact_redactions'],
            'selection': {'min_company_reviews_including_already_scored':minimum_company_reviews,
                          'max_per_company_this_export':max_per_company},
            'warnings':['Source employee classification and company attribution are not independently verified.',
                        'Basic emails/phone numbers are masked, but individual names and other sensitive data may remain: review ZIP before upload.',
                        'A repeated export BEFORE importing scores can include the same records; after import, five_v1 records are excluded.',
                        'This is not evidence for public company ranking or permission to republish full reviews.'],
        }
        if not chosen:
            self.stdout.write(json.dumps({'status':'NO_ELIGIBLE_RECORDS','database_writes':0,
                                          'hint':'Try --min-company-reviews 1 or check if scores already imported'}, ensure_ascii=False))
            return
        if out.exists() and options['overwrite']:
            # Output is a local file, never the database. Replacement is opt-in.
            pass
        tmp = out.with_name(out.name + '.tmp')
        try:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for idx, rows in enumerate(batches, start=1):
                    name = f'five_criteria_input_batch_{idx:03d}.jsonl'
                    contents = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
                    z.writestr(name, contents)
                    manifest['files'].append({'name':name,'records':len(rows), 'sha256':hashlib.sha256(contents).hexdigest()})
                z.writestr('README_FA.txt',
                    'این بسته، داده واقعی و خصوصی تجربه‌های کاری را برای امتیازدهی پژوهشی ChatGPT صادر کرده است.\n'
                    'پس از بررسی محتوا، ZIP را در گفتگو ارسال کنید.\n'
                    'خروجی امتیازدهی باید دقیقاً شامل ۵ معیار در dimensions باشد و source_url/hash بدون تغییر برگردد.\n'
                    'واردکردن: python manage.py import_five_criteria_ai FILE --dataset-id UNIQUE_BATCH --dry-run\n'
                    'پس از تایید و بکاپ: همان فرمان بدون --dry-run\n'
                    'پیش از ارسال، وجود نام افراد/داده حساس را بررسی کنید.\n')
                z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
        self.stdout.write(json.dumps({'status':'EXPORTED_PRIVATE_RESEARCH_INPUT',
                                      'output':str(out), 'selected':len(chosen),
                                      'companies':manifest['companies_selected'],
                                      'batches':len(batches),'already_scored_skipped':excluded['already_five_v1'],
                                      'contact_redacted_records':tally['contact_redactions'],
                                      'database_writes':0, 'paid_api_calls':0},ensure_ascii=False))
