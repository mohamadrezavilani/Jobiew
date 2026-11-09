"""Django integration test on disposable test DB; no live source or API."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from companies.models import Company
from experiences.models import PublicExperience
from criteria_v2.models import CriteriaReviewEvent, CriteriaAnalysis
from criteria_v2.engine_v207 import story_from_experience
from criteria_v2.management.commands.plan_dual6_rollout_v214 import (
    candidate_queryset, audit_queryset,
)


class RolloutDBTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(
            id='v214-test-company', source_url='https://example.test/v214',
            source_name='نمونه', display_name='نمونه')
        cls.user=get_user_model().objects.create_user('v214-reviewer',password='test-only')
        cls.story=('پرداخت حقوق به‌موقع و با مزایای مشخص انجام می‌شد و '
                   'همه اعضای تیم درباره قراردادشان اطلاعات روشن داشتند.')
        cls.exp=PublicExperience.objects.create(
            company=cls.company, source_url='https://example.test/v214/review',
            source_kind='work', body=cls.story, content_sha256='a'*64,
            copyright_review='pending',company_attribution_status='unverified')

    def state(self):
        qs=candidate_queryset()
        return audit_queryset(qs)

    def test_pending_not_ready(self):
        self.assertEqual(self.state()[0][2],'copyright_not_approved')

    def test_cleared_but_not_classified(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(
            copyright_review='approved',company_attribution_status='verified')
        self.assertEqual(self.state()[0][2],'classification_not_confirmed')

    def test_approved_latest_confirmation_ready(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(
            copyright_review='approved',company_attribution_status='verified')
        CriteriaReviewEvent.objects.create(
            experience=self.exp,reviewer=self.user,source_kind='work',
            criteria_version='work6_v2',source_content_sha256='a'*64,
            decision='confirmed')
        self.assertEqual(self.state()[0][2],'ready')

    def test_current_source_pilot_does_not_get_reprocessed(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(
            copyright_review='approved',company_attribution_status='verified')
        CriteriaReviewEvent.objects.create(
            experience=self.exp,reviewer=self.user,source_kind='work',
            criteria_version='work6_v2',source_content_sha256='a'*64,
            decision='confirmed')
        CriteriaAnalysis.objects.create(
            experience=self.exp,criteria_version='work6_v2',
            source_content_sha256='a'*64, model_name='pilot',
            prompt_version='v214',run_id='v214-pilot',
            review_status='pilot_unverified',raw_payload={})
        self.assertEqual(self.state()[0][2],'already_evaluated')

    def test_latest_exclusion_fails_closed(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(
            copyright_review='approved',company_attribution_status='verified')
        CriteriaReviewEvent.objects.create(
            experience=self.exp,reviewer=self.user,source_kind='work',
            criteria_version='work6_v2',source_content_sha256='a'*64,
            decision='confirmed')
        CriteriaReviewEvent.objects.create(
            experience=self.exp,reviewer=self.user,source_kind='work',
            criteria_version='work6_v2',source_content_sha256='a'*64,
            decision='excluded',note='این روایت باید از تحلیل کنار گذاشته شود')
        self.assertEqual(self.state()[0][2],'classification_not_confirmed')

    def test_read_only(self):
        before=CriteriaAnalysis.objects.count()
        self.state()
        self.assertEqual(CriteriaAnalysis.objects.count(),before)
