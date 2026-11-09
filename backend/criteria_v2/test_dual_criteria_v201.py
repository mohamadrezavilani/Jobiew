"""Regression coverage for dual-six v2.0.1 model/query fixes."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from companies.models import Company
from experiences.models import PublicExperience
from .models import CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent
from .views import pending_queryset


class ReviewQueueNullRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='dual-queue-v201', password='test-only')
        self.company = Company.objects.create(
            id='dual_v201_co', source_url='https://example.test/companies/co',
            source_name='شرکت', display_name='شرکت آزمون')
        self.work = PublicExperience.objects.create(
            company=self.company, source_url='https://example.test/experiences/work201',
            source_kind='work', title='روایت کاری', body='توضیح شرایط کار', content_sha256='a'*64)
        self.interview = PublicExperience.objects.create(
            company=self.company, source_url='https://example.test/experiences/interview201',
            source_kind='interview', title='روایت مصاحبه', body='توضیح شرایط مصاحبه', content_sha256='b'*64)

    def record(self, exp, decision, note=''):
        version = 'work6_v2' if exp.source_kind == 'work' else 'interview6_v2'
        return CriteriaReviewEvent.objects.create(
            experience=exp, reviewer=self.user, source_kind=exp.source_kind,
            criteria_version=version, source_content_sha256=exp.content_sha256,
            decision=decision, note=note)

    def test_unreviewed_are_pending_in_both_scopes(self):
        self.assertEqual(list(pending_queryset('work').values_list('pk', flat=True)), [self.work.pk])
        self.assertEqual(list(pending_queryset('interview').values_list('pk', flat=True)), [self.interview.pk])

    def test_latest_decision_and_source_change_control_pending(self):
        self.record(self.work, 'confirmed')
        self.assertFalse(pending_queryset('work').filter(pk=self.work.pk).exists())
        self.assertTrue(pending_queryset('interview').filter(pk=self.interview.pk).exists())
        self.record(self.work, 'needs_revision', note='دسته‌بندی این نظر نیاز به بازبینی مجدد دارد')
        self.assertTrue(pending_queryset('work').filter(pk=self.work.pk).exists())
        self.record(self.work, 'excluded', note='این نظر برای معیارها قابل استفاده نیست')
        self.assertFalse(pending_queryset('work').filter(pk=self.work.pk).exists())
        PublicExperience.objects.filter(pk=self.work.pk).update(content_sha256='c'*64)
        self.assertTrue(pending_queryset('work').filter(pk=self.work.pk).exists())

    def test_blank_json_default_is_valid_and_abstention_has_no_score(self):
        run = CriteriaAnalysis.objects.create(
            experience=self.work, criteria_version='work6_v2',
            source_content_sha256='a'*64, model_name='offline',
            prompt_version='draft-v201', run_id='test-v201-draft')
        self.assertEqual(run.raw_payload, {})
        abstain = CriteriaAxisScore.objects.create(
            analysis=run, key='work_compensation_fairness', score=None,
            confidence=0)
        self.assertEqual(abstain.evidence, [])
        self.assertIsNone(abstain.score)
