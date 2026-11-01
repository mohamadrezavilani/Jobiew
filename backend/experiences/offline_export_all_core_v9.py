"""Small, side-effect-free helpers for the v9 all-remaining offline export.

No DB access, network access, model calls, or paid API calls in this module.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from experiences.offline_export_core_v8 import redact_contacts


def make_private_record(obj):
    """Render the exact same v8 input schema for one Django PublicExperience."""
    body, b = redact_contacts(obj.body)
    title, t = redact_contacts(obj.title)
    job_title, j = redact_contacts(obj.job_title)
    masked = b or t or j
    pros, cons = [], []
    for original, target in ((obj.pros, pros), (obj.cons, cons)):
        for item in original if isinstance(original, list) else []:
            cleaned, changed = redact_contacts(str(item))
            target.append(cleaned)
            masked = masked or changed
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
    return record, bool(masked)


class BatchArchive:
    """Append JSONL batches into ONE output ZIP with checksums. Bounded memory."""
    def __init__(self, zip_file: ZipFile, batch_size: int):
        if not 1 <= batch_size <= 500:
            raise ValueError('batch_size must be 1..500')
        self.zip_file = zip_file
        self.batch_size = batch_size
        self.pending = []
        self.files = []
        self.total = 0
        self.companies = set()
        self.masked = 0

    def append(self, record: dict, masked: bool):
        self.pending.append(record)
        self.total += 1
        self.companies.add(record['company_id'])
        self.masked += bool(masked)
        if len(self.pending) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self.pending:
            return
        name = f'five_criteria_input_batch_{len(self.files)+1:03d}.jsonl'
        contents = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in self.pending).encode('utf-8')
        self.zip_file.writestr(name, contents)
        self.files.append({'name': name, 'records': len(self.pending), 'sha256': hashlib.sha256(contents).hexdigest()})
        self.pending.clear()

    def complete(self, excluded: dict, version: str):
        self.flush()
        manifest = {
            'format': 'workplace_five_v1_offline_input_v8',  # unchanged: existing scoring workflow
            'exporter': 'all_remaining_v9',
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'source': 'PostgreSQL/Django/PublicExperience',
            'criteria_version': version,
            'research_only_not_public': True,
            'database_writes': 0,
            'paid_api_calls': 0,
            'total_selected': self.total,
            'batch_size': self.batch_size,
            'files': self.files,
            'companies_selected': len(self.companies),
            'excluded': dict(excluded),
            'contact_redacted_records': self.masked,
            'selection': {
                'mode': 'ALL_ELIGIBLE_UNSCORED_WORK',
                'min_company_reviews': 1,
                'max_per_company': None,
                'max_records': None,
            },
            'warnings': [
                'Only source_kind=work, excluding rejected, marked duplicates, and blocked copyright.',
                'The work label alone does not establish employee experience; review content before scoring.',
                'Email and Iranian mobile contact masking is partial; other personal/sensitive text can remain.',
                'All contents are research-only: no automatically published company score is authorized.',
                'Upload the ONE archive once. Scoring may require separate conversation steps; do not assume all records can be scored in one chat response.',
            ],
        }
        self.zip_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        self.zip_file.writestr('README_FA.txt',
            'خروجی کاملِ نظرات کاری واجد شرایطی که هنوز نسخه five_v1 ندارند.\n'
            'همه بسته‌های JSONL در یک ZIP قرار دارند؛ هر فایل داخل آن فقط یک بخش از همان خروجی است.\n'
            'متن‌ها خصوصی‌اند؛ پیش از آپلود محتوای حساس را بررسی کنید.\n'
            'برای واردکردن خروجی امتیازدهی: python manage.py import_five_criteria_ai FILE --dataset-id UNIQUE --dry-run\n'
            'این فایل، امتیاز AI نیست؛ فقط ورودی امتیازدهی است.\n')
        return manifest
