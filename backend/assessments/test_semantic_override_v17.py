"""v17: research-only semantic override regression tests."""
import io
import json
import tempfile
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from assessments.models import AiAssessment, AiDimension, SemanticScoreOverride
from assessments.five_criteria_company_v7 import build_company_research_preview
from assessments.five_criteria_semantic_v17 import apply_active_semantic_overrides
from companies.models import Company
from experiences.models import PublicExperience

class SemanticOverrideV17Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(id='v17company',source_url='https://example.net/c/17',source_name='v17',display_name='آزمایش ۱۷')
        cls.exp=PublicExperience.objects.create(company=cls.company,source_url='https://example.net/r/17',source_kind='work',
            title='test',body='ساعات کاری مناسب و شرایط متعادل بود.',content_sha256='a'*64)
        cls.a=AiAssessment.objects.create(experience=cls.exp,criteria_version='five_v1',model_name='test',prompt_version='test',run_id='v17-run',publish_approved=False)
        cls.dim=AiDimension.objects.create(assessment=cls.a,key='work_conditions_pressure',score=3,confidence=50)

    def make_payload(self,action='revise',score=9):
        return {'review_id':'PG_17','dimension_id':self.dim.pk,'assessment_id':self.a.pk,
                'experience_id':self.exp.pk,'company_id':str(self.company.pk),'source_url':self.exp.source_url,
                'source_content_sha256':self.exp.content_sha256,'source_row_sha256':'c'*64,
                'criterion':'work_conditions_pressure','rating_direction':'10_IS_BETTER',
                'baseline_score':3,'proposed_score':score,'review_decision':action,
                'evidence_excerpt_exact':'ساعات کاری مناسب','semantic_rationale_fa':'در متن به مناسب بودن ساعات کاری اشاره شده است.'}

    def import_payload(self, payload, *args):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'pilot.jsonl';file.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            out=io.StringIO()
            call_command('import_semantic_first_axis_v17',str(file),'--batch-id','v17-pilot',*args,stdout=out)
            return json.loads(out.getvalue())

    def test_staged_does_not_change_any_mean_or_raw_score(self):
        before=build_company_research_preview(self.company)['criteria'][0]['mean_provisional']
        self.assertEqual(before,3)
        r=self.import_payload(self.make_payload())
        self.assertEqual(r['imported'],1)
        self.assertEqual(SemanticScoreOverride.objects.count(),1)
        self.assertEqual(build_company_research_preview(self.company)['criteria'][0]['mean_provisional'],3)
        self.dim.refresh_from_db(); self.assertEqual(self.dim.score,3)

    def test_activate_changes_private_mean_and_preserves_raw(self):
        self.import_payload(self.make_payload())
        out=io.StringIO()
        call_command('activate_semantic_first_axis_v17','--batch-id','v17-pilot',stdout=out)
        self.assertEqual(SemanticScoreOverride.objects.filter(status='active_provisional').count(),0)
        call_command('activate_semantic_first_axis_v17','--batch-id','v17-pilot','--confirm-provisional',stdout=out)
        self.assertEqual(build_company_research_preview(self.company)['criteria'][0]['mean_provisional'],9)
        self.dim.refresh_from_db();self.assertEqual(self.dim.score,3)
        self.assertFalse(self.a.publish_approved)
        self.assertEqual(SemanticScoreOverride.objects.count(),2)
        call_command('activate_semantic_first_axis_v17','--batch-id','v17-pilot','--confirm-provisional',stdout=io.StringIO())
        self.assertEqual(SemanticScoreOverride.objects.count(),2)

    def test_abstain_has_no_numeric_score(self):
        self.import_payload(self.make_payload('abstain',None))
        call_command('activate_semantic_first_axis_v17','--batch-id','v17-pilot','--confirm-provisional',stdout=io.StringIO())
        crit=build_company_research_preview(self.company)['criteria'][0]
        self.assertIsNone(crit['mean_provisional'])
        self.assertEqual(crit['n_provisional_abstentions'],1)

    def test_dry_run_idempotent(self):
        result=self.import_payload(self.make_payload(),'--dry-run')
        self.assertEqual(result['to_import'],1)
        self.assertEqual(SemanticScoreOverride.objects.count(),0)
        self.import_payload(self.make_payload())
        result=self.import_payload(self.make_payload())
        self.assertEqual(result['existing'],1)
        self.assertEqual(result['imported'],0)

    def test_stale_hash_blocked_and_no_unverified_activation(self):
        payload=self.make_payload();payload['source_content_sha256']='b'*64
        with self.assertRaises(CommandError):self.import_payload(payload)
        self.import_payload(self.make_payload())
        self.exp.content_sha256='b'*64;self.exp.save(update_fields=['content_sha256'])
        with self.assertRaises(CommandError):call_command('activate_semantic_first_axis_v17','--batch-id','v17-pilot','--confirm-provisional',stdout=io.StringIO())
        self.assertEqual(SemanticScoreOverride.objects.filter(status='active_provisional').count(),0)

    def test_override_not_considered_human_approval(self):
        self.import_payload(self.make_payload())
        call_command('activate_semantic_first_axis_v17','--batch-id','v17-pilot','--confirm-provisional',stdout=io.StringIO())
        crit=build_company_research_preview(self.company)['criteria'][0]
        self.assertIsNone(crit['score'])
        self.assertEqual(crit['n_verified_independent'],0)

    def test_pure_overlay_keeps_without_active(self):
        rows=[dict(dimension_id=self.dim.pk,content_hash='a'*64,score=3)]
        self.assertEqual(apply_active_semantic_overrides(rows)[0]['score'],3)
