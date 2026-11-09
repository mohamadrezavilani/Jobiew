"""All AI calls mocked; disposable Django test database; no paid API."""
import json
from unittest.mock import Mock
from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company
from criteria_v2.management.commands.run_dual6_batch_v215 import (
    _source_decision, execute_candidate,
)
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent
from criteria_v2.registry import AXES
from experiences.models import PublicExperience

MODEL = 'claude-sonnet-4-6'
STORY = ('در مجموعه، حقوق هر ماه با دو ماه تأخیر واریز می‌شد و مدیر مستقیم هم '
         'هیچ توضیح روشنی دربارهٔ این تأخیرهای مستمر نمی‌داد؛ بااین‌حال '
         'همکاران از نظر فنی با یکدیگر همکاری داشتند.')
QUOTE = 'حقوق هر ماه با دو ماه تأخیر واریز می‌شد'


def reply(*, kind='work', detected='work', invalid_quote=False):
    dims = {axis.key:{'score':None,'confidence':0,'evidence':'',
                      'explanation':'در روایت شاهد معتبر و کافی برای این محور وجود ندارد'}
            for axis in AXES[kind]}
    dims['work_compensation_fairness']={'score':2,'confidence':90,
       'evidence':'دروغی که در متن وجود ندارد' if invalid_quote else QUOTE,
       'explanation':'تأخیرهای مکرر پرداخت باعث کاهش امتیاز عدالت پرداخت شده است'}
    p={'detected_kind':detected,'kind_confidence':95,'dimensions':dims}
    return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(p,ensure_ascii=False)}],
            'usage':{'input_tokens':100,'output_tokens':80}}


class BulkV215DatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(
            id='bulk-v215-test',source_url='https://example.test/v215',
            source_name='آزمایشی', display_name='شرکت آزمایشی')
        cls.user=get_user_model().objects.create_user('bulk-v215-test-reviewer',password='mock-only')
        cls.exp=PublicExperience.objects.create(
            company=cls.company, source_url='https://example.test/v215/story',
            source_kind='work',title='test',body=STORY,content_sha256='a'*64,
            copyright_review='pending',company_attribution_status='unverified')

    def clear_source(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(
            copyright_review='approved',company_attribution_status='verified')
        CriteriaReviewEvent.objects.create(
            experience=self.exp,reviewer=self.user,source_kind='work',
            criteria_version='work6_v2',source_content_sha256='a'*64,
            decision='confirmed')

    def test_pending_gate_suppresses_inference(self):
        inference=Mock(return_value=reply())
        result=execute_candidate(self.exp.pk,MODEL,inference=inference)
        inference.assert_not_called()
        self.assertEqual(result['reason'],'copyright_not_approved')
        self.assertFalse(CriteriaAnalysis.objects.exists())

    def test_attribution_gate_independent(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='approved')
        self.assertEqual(_source_decision(PublicExperience.objects.get(pk=self.exp.pk),STORY),
                         'attribution_not_verified')

    def test_classification_gate_independent(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(
            copyright_review='approved',company_attribution_status='verified')
        self.assertEqual(_source_decision(PublicExperience.objects.get(pk=self.exp.pk),STORY),
                         'classification_not_confirmed')

    def test_complete_saves_six_and_repeat_cost_zero(self):
        self.clear_source()
        inference=Mock(return_value=reply())
        result=execute_candidate(self.exp.pk,MODEL,inference=inference)
        self.assertEqual(result['outcome'],'SAVED')
        self.assertEqual(CriteriaAnalysis.objects.count(),1)
        self.assertEqual(CriteriaAxisScore.objects.count(),6)
        row=CriteriaAnalysis.objects.get()
        self.assertEqual(row.review_status,'unreviewed')
        self.assertEqual(row.axis_scores.get(key='work_compensation_fairness').score,2)
        self.assertNotIn(STORY, json.dumps(row.raw_payload,ensure_ascii=False))
        result2=execute_candidate(self.exp.pk,MODEL,inference=inference)
        self.assertEqual(result2['reason'],'already_evaluated')
        self.assertEqual(inference.call_count,1)
        self.assertFalse(CriteriaAxisScore.objects.filter(semantic_status='approved').exists())

    def test_kind_disagreement_does_not_store_axis_scores(self):
        self.clear_source()
        result=execute_candidate(self.exp.pk,MODEL,
                  inference=lambda req:reply(detected='interview'))
        self.assertEqual(result['review_status'],'needs_review')
        self.assertEqual(CriteriaAxisScore.objects.count(),0)

    def test_invalid_quote_fails_and_does_not_retry(self):
        self.clear_source()
        inference=Mock(return_value=reply(invalid_quote=True))
        self.assertEqual(execute_candidate(self.exp.pk,MODEL,inference=inference)['outcome'],'FAILED')
        self.assertEqual(CriteriaAnalysis.objects.get().review_status,'failed')
        self.assertEqual(CriteriaAxisScore.objects.count(),0)
        self.assertEqual(execute_candidate(self.exp.pk,MODEL,inference=inference)['outcome'],'SKIPPED')
        self.assertEqual(inference.call_count,1)

    def test_network_error_records_failure_without_story_leak(self):
        self.clear_source()
        def failed(req):raise RuntimeError('ANTHROPIC_HTTP_503')
        result=execute_candidate(self.exp.pk,MODEL,inference=failed)
        self.assertEqual(result['outcome'],'FAILED')
        self.assertEqual(result['reason'],'ANTHROPIC_HTTP_503')
        self.assertEqual(CriteriaAnalysis.objects.get().review_status,'failed')
        self.assertNotIn(STORY,str(CriteriaAnalysis.objects.get().raw_payload))

    def test_source_changed_during_call_is_stale(self):
        self.clear_source()
        def change(req):
            PublicExperience.objects.filter(pk=self.exp.pk).update(
                 content_sha256='b'*64)
            return reply()
        result=execute_candidate(self.exp.pk,MODEL,inference=change)
        self.assertEqual(result['outcome'],'STALE')
        self.assertEqual(CriteriaAnalysis.objects.get().review_status,'stale')
        self.assertFalse(CriteriaAxisScore.objects.exists())

    def test_approval_revoked_during_call_is_stale(self):
        self.clear_source()
        def revoke(req):
            PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='pending')
            return reply()
        result=execute_candidate(self.exp.pk,MODEL,inference=revoke)
        self.assertEqual(result['outcome'],'STALE')
        self.assertFalse(CriteriaAxisScore.objects.exists())

    def test_classification_revoked_during_call_is_stale(self):
        self.clear_source()
        def revoke(req):
            CriteriaReviewEvent.objects.create(
                experience=self.exp,reviewer=self.user,source_kind='work',
                criteria_version='work6_v2',source_content_sha256='a'*64,
                decision='excluded',note='این تجربه برای تحلیل مناسب نیست')
            return reply()
        result=execute_candidate(self.exp.pk,MODEL,inference=revoke)
        self.assertEqual(result['outcome'],'STALE')
        self.assertFalse(CriteriaAxisScore.objects.exists())
