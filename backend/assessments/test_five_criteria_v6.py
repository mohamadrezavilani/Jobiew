"""Five-criteria research import and historical compatibility regression tests."""
import json
import tempfile
from io import StringIO
from pathlib import Path
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from assessments.models import (
    AiAssessment, AiDimension, DIMENSIONS, LEGACY_DIMENSIONS,
    FIVE_CRITERIA_VERSION, LEGACY_CRITERIA_VERSION,
)
from companies.models import Company
from experiences.models import PublicExperience
from voting.services import validate_scores, VoteDenied

class FiveCriteriaTests(TestCase):
    def setUp(self):
        company = Company.objects.create(id='five-qa', source_url='https://example.org/company',
            source_name='Research sample', display_name='نمونه تست')
        self.exp = PublicExperience.objects.create(company=company,
            source_url='https://example.org/experience', source_kind='work',
            title='نمونه آزمایشی', body='شرایط کاری مناسب است.', content_sha256='a' * 64)

    def sample(self):
        return {'source_url': self.exp.source_url, 'source_content_sha256': 'a'*64,
            'dimensions': {key: {'score': (6 if key == 'work_conditions_pressure' else None),
               'confidence_evidence_support_unvalidated': (65 if key == 'work_conditions_pressure' else 0),
               'evidence': ('شرایط کاری مناسب است.' if key == 'work_conditions_pressure' else ''),
               'status': ('SCORED_PROVISIONAL' if key == 'work_conditions_pressure' else 'NO_EVIDENCE_OR_EXCLUDED')}
               for key, _ in DIMENSIONS}}

    def run_import(self, rows, dry_run=False):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t)/'rows.jsonl'
            f.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows), encoding='utf-8')
            out = StringIO()
            call_command('import_five_criteria_ai', str(f), dry_run=dry_run, stdout=out)
            return json.loads(out.getvalue())

    def test_active_keys_are_five_and_legacy_keys_remain_supported(self):
        self.assertEqual(len(DIMENSIONS),5)
        self.assertEqual(len(LEGACY_DIMENSIONS),9)
        self.assertEqual(AiDimension._meta.get_field('key').choices.__len__(),14)
        self.assertEqual(AiAssessment._meta.get_field('criteria_version').get_default(), FIVE_CRITERIA_VERSION)

    def test_import_dry_run_idempotent_and_unpublished(self):
        row = self.sample()
        self.assertEqual(self.run_import([row], dry_run=True)['imported'], 1)
        self.assertEqual(AiAssessment.objects.count(),0)
        self.assertEqual(self.run_import([row])['imported'],1)
        self.assertEqual(self.run_import([row])['existing'],1)
        assessment = AiAssessment.objects.get()
        self.assertEqual(assessment.criteria_version, FIVE_CRITERIA_VERSION)
        self.assertFalse(assessment.publish_approved)
        self.assertEqual(assessment.independent_review_status,'unreviewed')
        self.assertEqual(assessment.dimensions.count(),5)
        self.assertEqual(assessment.dimensions.get(key='management_environment').score,None)
        self.assertEqual(assessment.dimensions.get(key='work_conditions_pressure').confidence,65)

    def test_bad_or_changed_source_is_not_written(self):
        row=self.sample()
        row['source_content_sha256']='b'*64
        self.assertEqual(self.run_import([row])['source_hash_mismatch'],1)
        self.assertFalse(AiAssessment.objects.exists())

    def test_invalid_legacy_or_fake_evidence_rejected(self):
        row=self.sample();row['dimensions']['workload']={'score':6}
        self.assertEqual(self.run_import([row])['invalid'],1)
        row=self.sample();row['dimensions']['work_conditions_pressure']['evidence']=''
        self.assertEqual(self.run_import([row])['invalid'],1)
        self.assertFalse(AiAssessment.objects.exists())

    def test_new_votes_legacy_rejected(self):
        self.assertEqual(validate_scores({'work_conditions_pressure':8}), {'work_conditions_pressure':8})
        with self.assertRaises(VoteDenied):
            validate_scores({'workload':8})

    def test_public_company_shows_criteria_but_no_scores_or_review_text(self):
        response=self.client.get(reverse('company-detail',args=[self.exp.company_id]))
        self.assertEqual(response.status_code,200)
        for key,label in DIMENSIONS:
            self.assertContains(response,label)
        self.assertNotContains(response,'شرایط کاری مناسب است.')
        self.assertContains(response,'اطلاعات تأییدشده')

    def test_import_legacy_explicitly_versioned(self):
        row={'source_url':self.exp.source_url, 'source_content_sha256':'a'*64,
             'model':'history','timestamp_utc':'2026-10-01','result':{'dimensions':{'workload':{'score':2,'confidence':50,'evidence':[]}}}}
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'old.jsonl';path.write_text(json.dumps(row),encoding='utf-8')
            call_command('import_ai_pilots',str(path),stdout=StringIO())
        self.assertEqual(AiAssessment.objects.get().criteria_version, LEGACY_CRITERIA_VERSION)
        self.assertEqual(AiDimension.objects.get().key,'workload')
