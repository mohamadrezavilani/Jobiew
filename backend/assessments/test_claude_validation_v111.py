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
    def test_one_paid_request_is_separate_and_idempotent(self,api):
        api.return_value=self.fake
        r=self.client.post(self.url,{'force':'false'})
        self.assertEqual(r.status_code,200,r.content[:300]);self.assertTrue(r.json()['ok'])
        run=ClaudeValidationRun.objects.get()
        self.assertEqual(run.input_tokens,1024)
        self.assertEqual(set(run.claude_results),{key for key,_ in DIMENSIONS})
        self.assessment.refresh_from_db();self.assertFalse(self.assessment.publish_approved)
        self.assertFalse(self.assessment.dimensions.filter(semantic_status='approved').exists())
        self.assertEqual(AiDimension.objects.get(assessment=self.assessment,key=DIMENSIONS[0][0]).score,5)
        self.assertEqual(run.comparison[DIMENSIONS[0][0]]['delta'],2)
        again=self.client.post(self.url,{'force':'false'})
        self.assertEqual(again.status_code,200);self.assertFalse(again.json()['called'])
        self.assertEqual(api.call_count,1)
        self.assertEqual(ClaudeValidationRun.objects.count(),1)

    @patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test-not-real','JOBIEW_CLAUDE_VALIDATION_LIMIT':'1'})
    @patch('assessments.claude_validation_v111.call_claude')
    def test_quota_prevents_unexpected_second_bill(self,api):
        api.return_value=self.fake
        self.client.post(self.url,{'force':'false'})
        second=self.client.post(self.url,{'force':'true'})
        self.assertEqual(second.status_code,400)
        self.assertIn('سقف',second.json()['message'])
        self.assertEqual(api.call_count,1)

    @patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test-not-real'})
    @patch('assessments.claude_validation_v111.call_claude')
    def test_malformed_response_records_failure_not_score(self,api):
        api.return_value={'stop_reason':'end_turn','content':[{'type':'text','text':'bad json'}]}
        r=self.client.post(self.url,{'force':'false'})
        self.assertEqual(r.status_code,502)
        run=ClaudeValidationRun.objects.get();self.assertEqual(run.status,'failed')
        self.assessment.refresh_from_db();self.assertFalse(self.assessment.publish_approved)
        self.assertEqual(run.claude_results,{})

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
