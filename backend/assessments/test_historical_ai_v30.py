import json
import tempfile
from io import StringIO
from pathlib import Path
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, RequestFactory
from companies.models import Company
from experiences.models import PublicExperience
from assessments.models import AiAssessment, AiDimension
from assessments.admin import AiAssessmentAdmin


class HistoricalAiTests(TestCase):
    def setUp(self):
        c = Company.objects.create(id='c30', source_url='https://example.org/co',
            source_name='نمونه', display_name='نمونه')
        self.e = PublicExperience.objects.create(company=c, source_url='https://example.org/e',
            source_kind='work', title='نظر', body='شاهد داخلی', content_sha256='abc123')

    def test_hash_mismatch_skipped_without_side_effects(self):
        row = self._example()
        row['source_content_sha256'] = 'wrong'
        text = self._import([row])
        self.assertIn('"source_hash_mismatch": 1', text)
        self.assertEqual(AiAssessment.objects.count(), 0)

    def test_dry_run_and_idempotent_import_keep_private(self):
        row = self._example()
        self._import([row], dry_run=True)
        self.assertEqual(AiAssessment.objects.count(), 0)
        self._import([row]); self._import([row])
        self.assertEqual(AiAssessment.objects.count(), 1)
        a = AiAssessment.objects.get()
        self.assertFalse(a.publish_approved)
        self.assertEqual(a.independent_review_status, 'unreviewed')
        self.assertEqual(AiDimension.objects.count(), 2)

    def test_admin_cannot_approve_publication(self):
        ma = AiAssessmentAdmin(AiAssessment, AdminSite())
        request = RequestFactory().get('/admin/')
        self.assertIn('publish_approved', ma.get_readonly_fields(request))
        self.assertFalse(ma.has_change_permission(request))

    def _example(self):
        return {'source_url': self.e.source_url, 'source_content_sha256': 'abc123',
            'model': 'claude-haiku-4-5', 'prompt_version': 'v30-test',
            'timestamp_utc': '2026-10-19', 'result': {'dimensions': {
                'career_growth': {'score': 8, 'confidence': 90, 'evidence': [{'quote': 'شاهد داخلی', 'field': 'body'}]},
                'job_stability': {'score': None, 'confidence': 0, 'evidence': []},
            }}}

    def _import(self, rows, dry_run=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pilot.jsonl'
            path.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows), encoding='utf8')
            output=StringIO()
            call_command('import_ai_pilots', str(path), dry_run=dry_run, stdout=output)
            return output.getvalue()
