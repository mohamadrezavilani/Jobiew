"""All tests use a mocked API. NEVER sends a paid Claude request."""
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension, DIMENSIONS
from assessments.claude_validation_models_v111 import ClaudeValidationRun
from assessments.claude_validation_v111 import build_comparison, validated_dimensions
from companies.models import Company
from experiences.models import PublicExperience


class ClaudeValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff=get_user_model().objects.create_superuser('claude111', 'test111@example.org','pwd')
        cls.co=Company.objects.create(id='c111',source_url='https://example.org/c111',
              source_name='company',display_name='شرکت آزمایش',identity_status='verified',tech_status='verified')
        cls.exp=PublicExperience.objects.create(company=cls.co,source_url='https://example.org/e111',
              source_kind='work',title='تجربه کار',job_title='توسعه دهنده',
              body='محیط کاری دوستانه بود ولی ساعات اضافه کاری زیاد بود و یادگیری کم بود.',
              content_sha256='a'*64)
        cls.assessment=AiAssessment.objects.create(experience=cls.exp,criteria_version='five_v1',
             model_name='original-AI',prompt_version='five_v1',run_id='claude-test-111')
        for i,(key,_) in enumerate(DIMENSIONS):
            AiDimension.objects.create(assessment=cls.assessment,key=key,
                score=(None if i==4 else 5+i),confidence=0 if i==4 else 70,
                explanation='توضیح نسخه اصلی',evidence=[])

    def setUp(self):
        self.client.force_login(self.staff)
        self.url=reverse('admin:assessments_aiassessment_claude_run',args=[self.assessment.pk])
        self.fake={'stop_reason':'end_turn','usage':{'input_tokens':1024,'output_tokens':700},
            'content':[{'type':'text','text':json.dumps({'dimensions':[
                {'key':key,'score':None if i==4 else 7,'confidence':0 if i==4 else 80,
                 'reason':'بر اساس شواهد کاربر، این نمره پیشنهاد می‌شود.',
                 'evidence':'' if i==4 else 'محیط کاری دوستانه بود'}
                for i,(key,_) in enumerate(DIMENSIONS)]},ensure_ascii=False)}]}

    @patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test-not-real','JOBIEW_CLAUDE_VALIDATION_LIMIT':'5'})
    @patch('assessments.claude_validation_v111.call_claude')
    def test_legacy_paid_request_blocked_before_any_api_call(self,api):
        for force in ('false', 'true'):
            r=self.client.post(self.url,{'force':force})
            self.assertEqual(r.status_code,409,r.content[:300])
            self.assertEqual(r.json()['error'],'legacy_scoring_suspended')
        api.assert_not_called()
        self.assertFalse(ClaudeValidationRun.objects.exists())
        self.assessment.refresh_from_db()
        self.assertFalse(self.assessment.publish_approved)
        self.assertEqual(AiDimension.objects.get(
            assessment=self.assessment,key=DIMENSIONS[0][0]).score,5)

    @patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test-not-real','JOBIEW_CLAUDE_VALIDATION_LIMIT':'1'})
    @patch('assessments.claude_validation_v111.call_claude')
    def test_legacy_quota_or_force_cannot_restart_paid_analysis(self,api):
        for force in ('false','true'):
            second=self.client.post(self.url,{'force':force})
            self.assertEqual(second.status_code,409)
            self.assertEqual(second.json()['error'],'legacy_scoring_suspended')
        api.assert_not_called()
        self.assertEqual(ClaudeValidationRun.objects.count(),0)

    @patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test-not-real'})
    @patch('assessments.claude_validation_v111.call_claude')
    def test_legacy_malformed_data_not_sent_to_paid_api(self,api):
        api.return_value={'stop_reason':'end_turn','content':[{'type':'text','text':'bad json'}]}
        r=self.client.post(self.url,{'force':'false'})
        self.assertEqual(r.status_code,409)
        api.assert_not_called()
        self.assertFalse(ClaudeValidationRun.objects.exists())
        self.assessment.refresh_from_db()
        self.assertFalse(self.assessment.publish_approved)

    def test_public_or_nonstaff_cannot_run(self):
        self.client.force_login(get_user_model().objects.create_user('regular111','regular@example.org','pwd'))
        self.assertIn(self.client.post(self.url,{'force':'false'}).status_code,(302,403))
        self.assertEqual(ClaudeValidationRun.objects.count(),0)

    def test_schema_rejects_invented_score_and_key(self):
        invalid=dict(self.fake)
        payload=json.loads(invalid['content'][0]['text'])
        payload['dimensions'][0]['score']=11
        invalid['content']=[{'type':'text','text':json.dumps(payload)}]
        with self.assertRaises(ValueError):validated_dimensions(invalid,self.exp.body)

    def test_views_display_comparison_and_batch(self):
        index=reverse('admin:assessments_aiassessment_claude_dashboard')
        detail=reverse('admin:assessments_aiassessment_claude_detail',args=[self.assessment.pk])
        self.assertContains(self.client.get(index),'صحت‌سنجی اختیاری با Claude')
        self.assertContains(self.client.get(detail),'مقایسهٔ پنج شاخص')
        self.assertNotContains(self.client.get(detail),'sk-ant-')
