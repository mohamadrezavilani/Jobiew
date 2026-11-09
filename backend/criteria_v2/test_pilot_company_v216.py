"""Disposable Django acceptance of company-scoped private pilot roll-up."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from experiences.models import PublicExperience
from .engine_v207 import story_digest, story_from_experience
from .models import CriteriaAnalysis, CriteriaAxisScore, CriteriaScoreReviewEvent
from .pilot_import_v212 import ENGINE
from .registry import axes_for, version_for

FLAGS = {'JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED': '1',
         'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0'}
STORY = 'در این شرکت حقوق هر ماه با دو ماه تأخیر پرداخت می‌شد و هیچ توضیح شفافی درباره آن وجود نداشت.'
QUOTE = 'حقوق هر ماه با دو ماه تأخیر پرداخت می‌شد'
INTERVIEW_STORY = 'مصاحبه‌گر با احترام با من رفتار کرد و سؤال‌های مرتبط با شغل پرسید و نتیجه را سریع اعلام کرد.'
INTERVIEW_QUOTE = 'مصاحبه‌گر با احترام با من رفتار کرد'


@override_settings(DEBUG=True)
class PrivatePilotCompanyV216Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='v216-test-company', source_url='https://example.invalid/v216',
            source_name='نمونه', display_name='شرکت پایلوت وی ۲۱۶')
        cls.other_company = Company.objects.create(
            id='v216-other-company', source_url='https://example.invalid/v216-other',
            source_name='دیگری', display_name='شرکت دیگر')
        cls.staff = get_user_model().objects.create_superuser(
            username='v216-superuser', email='v216@example.invalid', password='test-only')
        cls.nonstaff = get_user_model().objects.create_user(
            username='v216-user', password='test-only')
        cls.work = cls.make_experience(cls.company, 'work', STORY, 'one')
        cls.interview = cls.make_experience(cls.company, 'interview', INTERVIEW_STORY, 'two')
        cls.other = cls.make_experience(cls.other_company, 'work', STORY, 'three')
        cls.work_run = cls.make_pilot(cls.work, 2, QUOTE, 'work-001')
        cls.interview_run = cls.make_pilot(cls.interview, 9, INTERVIEW_QUOTE, 'interview-001')
        cls.other_run = cls.make_pilot(cls.other, 7, QUOTE, 'work-002')

    @staticmethod
    def make_experience(company, kind, body, name):
        return PublicExperience.objects.create(
            company=company,
            source_url='https://example.invalid/v216/'+name,
            source_kind=kind, title='فقط برای تست', body=body,
            content_sha256='a'*64, copyright_review='pending',
            company_attribution_status='unverified', independence_status='unknown')

    @staticmethod
    def make_pilot(exp, score, quote, name):
        obj = CriteriaAnalysis.objects.create(
            experience=exp, criteria_version=version_for(exp.source_kind),
            source_content_sha256=exp.content_sha256,
            model_name='synthetic-v216', prompt_version='unit-test',
            run_id='synthetic-v216-'+name, review_status='pilot_unverified',
            raw_payload={'engine': ENGINE, 'case_id': name,
                         'story_sha256': story_digest(story_from_experience(exp)),
                         'human_reference': 'NOT_INDEPENDENT'})
        for i, axis in enumerate(axes_for(exp.source_kind)):
            CriteriaAxisScore.objects.create(
                analysis=obj, key=axis.key, score=score if i==0 else None,
                confidence=90 if i==0 else 0,
                evidence=[quote] if i==0 else [],
                explanation='بررسی روایت آزمایشی و شواهد مستقیم برای این معیار',
                semantic_status='unreviewed')
        return obj

    def url(self, company=None):
        return reverse('dual-pilot-company-v216', args=[company.pk if company else self.company.pk])

    def test_staff_only_and_private_headers(self):
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(self.url()).status_code,403)
            self.client.force_login(self.nonstaff)
            self.assertEqual(self.client.get(self.url()).status_code,403)
            self.client.force_login(self.staff)
            r=self.client.get(self.url())
        self.assertEqual(r.status_code,200)
        self.assertIn('no-store',r['Cache-Control'])
        self.assertIn('noindex',r['X-Robots-Tag'])

    @override_settings(DEBUG=False)
    def test_closed_outside_debug(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(self.url()).status_code,404)

    def test_closed_when_feature_flag_off(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', {**FLAGS,'JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED':'0'}):
            self.assertEqual(self.client.get(self.url()).status_code,404)

    def test_closed_if_publication_enabled(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', {**FLAGS,'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1'}):
            self.assertEqual(self.client.get(self.url()).status_code,404)

    def test_scopes_and_nulls_not_zero(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ',FLAGS):
            r=self.client.get(self.url())
        self.assertEqual(r.context['work']['pilot_valid_cases'],1)
        self.assertEqual(r.context['work']['pilot_numeric_scores'],1)
        self.assertEqual(r.context['work']['pilot_abstentions'],5)
        self.assertEqual(r.context['work']['axes'][0]['score'],2)
        self.assertEqual(r.context['work']['axes'][1]['score'],None)
        self.assertEqual(r.context['interview']['pilot_valid_cases'],1)
        self.assertEqual(r.context['interview']['axes'][0]['score'],9)
        self.assertNotContains(r,QUOTE)
        self.assertNotContains(r,INTERVIEW_QUOTE)
        self.assertNotContains(r,STORY)
        self.assertNotContains(r,'شرکت دیگر')
        self.assertContains(r,'غیرقابل انتشار')

    def test_stale_source_does_not_contribute(self):
        self.client.force_login(self.staff)
        PublicExperience.objects.filter(pk=self.work.pk).update(content_sha256='b'*64)
        with patch.dict('os.environ',FLAGS):
            r=self.client.get(self.url())
        self.assertEqual(r.context['work']['pilot_invalid_cases'],1)
        self.assertIsNone(r.context['work']['axes'][0]['score'])
        self.assertEqual(r.context['interview']['axes'][0]['score'],9)

    def test_blocked_rights_excluded_and_other_company_isolated(self):
        self.client.force_login(self.staff)
        PublicExperience.objects.filter(pk=self.work.pk).update(copyright_review='blocked')
        with patch.dict('os.environ',FLAGS):
            r=self.client.get(self.url())
        self.assertEqual(r.context['work']['pilot_invalid_cases'],1)
        with patch.dict('os.environ',FLAGS):
            other=self.client.get(self.url(self.other_company))
        self.assertEqual(other.context['work']['axes'][0]['score'],7)

    def test_unrelated_nonpilot_run_never_contributes(self):
        CriteriaAnalysis.objects.create(
            experience=self.work, criteria_version='work6_v2',
            source_content_sha256=self.work.content_sha256,
            model_name='other', prompt_version='other',
            run_id='other-v216', review_status='unreviewed',
            raw_payload={'engine': 'other'})
        self.client.force_login(self.staff)
        with patch.dict('os.environ',FLAGS):
            r=self.client.get(self.url())
        self.assertEqual(r.context['work']['pilot_valid_cases'],1)

    def test_public_page_never_uses_pilot_scores(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ',FLAGS):
            self.client.get(self.url())
            r=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertNotContains(r,QUOTE)
        self.assertNotContains(r,'synthetic-v216')

    def test_never_writes_and_post_disallowed(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ',FLAGS):
            self.assertEqual(self.client.post(self.url()).status_code,405)
            self.client.get(self.url())
        self.work_run.refresh_from_db()
        self.assertEqual(self.work_run.review_status,'pilot_unverified')
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(),0)
        self.assertFalse(CriteriaAxisScore.objects.filter(semantic_status='approved').exists())
