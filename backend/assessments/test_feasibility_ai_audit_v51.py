import csv
import json
import tempfile
from io import StringIO
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from companies.models import Company
from experiences.models import PublicExperience
from assessments.models import AiAssessment, AiDimension


class HistoricalFeasibilityAuditV51Tests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(id='v51co', source_url='https://example.org/company',
                                              source_name='پایلوت', display_name='پایلوت')
        self.exp = PublicExperience.objects.create(company=self.company,
            source_url='https://example.org/work', source_kind='work', title='حقوق کم',
            body='پرداخت حقوق به موقع بود', content_sha256='abcd')
        self.ai = AiAssessment.objects.create(experience=self.exp, model_name='old-model',
                       prompt_version='old-prompt', run_id='historic-v51', criteria_version='legacy9')
        AiDimension.objects.create(assessment=self.ai, key='market_pay_competitiveness',
            score=8, confidence=95, evidence=[{'quote':'متن غیر موجود'}], semantic_status='unreviewed')
        AiDimension.objects.create(assessment=self.ai, key='job_stability',
            score=None, confidence=0, evidence=[])

    def test_export_marks_mechanical_flags_and_no_score_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'report'
            pilot = Path(tmp) / 'pilot.csv'
            pilot.write_text('company_id,company_name\nv51co,پایلوت\n', encoding='utf8')
            call_command('feasibility_ai_audit_v51', out=str(out), pilot_csv=str(pilot), stdout=StringIO())
            manifest = json.loads((out/'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['historical_assessments'],1)
            self.assertEqual(manifest['dimension_rows_in_review_worksheet'],9)
            self.assertEqual(manifest['pilot_companies_with_historical_ai'],1)
            self.assertEqual(manifest['flag_counts']['missing_dimension_record'],7)
            self.assertEqual(manifest['flag_counts']['literal_evidence_not_found_in_review'],1)
            self.assertEqual(manifest['database_writes'],0)
            with (out/'pilot_ai_coverage.csv').open(encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),9)
            self.assertEqual(next(x for x in rows if x['dimension']=='job_stability')
                             ['historical_assessed_experiences_with_score'],'0')
            private=(out/'historical_ai_source_PRIVATE.jsonl').read_text(encoding='utf8')
            self.assertIn('پرداخت حقوق به موقع بود',private)
            self.assertEqual(AiAssessment.objects.count(),1)
            self.assertEqual(AiDimension.objects.count(),2)
            self.assertFalse(self.ai.publish_approved)

    def test_refuses_overwrite_without_db_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'report';out.mkdir()
            with self.assertRaises(CommandError):
                call_command('feasibility_ai_audit_v51',out=str(out),stdout=StringIO())
            self.assertEqual(AiDimension.objects.count(),2)

    def test_empty_historical_set_produces_zero_not_fake_scores(self):
        AiDimension.objects.all().delete()  # Test data only
        AiAssessment.objects.all().delete()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';call_command('feasibility_ai_audit_v51',out=str(out),stdout=StringIO())
            summary=json.loads((out/'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(summary['historical_assessments'],0)
            self.assertEqual(summary['dimension_rows_in_review_worksheet'],0)
