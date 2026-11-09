"""Django acceptance for private, read-only, never-published pilot dashboard."""
import hashlib
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

STORY = ('حقوق هر ماه با تاخیر دو هفته پرداخت شد و مدیر درباره پرداخت‌ها توضیحی ارائه نکرد. '
         'از طرفی درباره آموزش مهارت‌های تازه در این تجربه هیچ اشاره‌ای نشده است.')
EVIDENCE = 'حقوق هر ماه با تاخیر دو هفته پرداخت شد'
FLAGS = {'JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED':'1',
         'JOBIEW_DUAL6_PUBLICATION_ENABLED':'0'}


@override_settings(DEBUG=True)
class PilotDashboardV213Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='pilot-v213-company', source_url='https://example.invalid/pilot-v213',
            source_name='آزمایشی', display_name='شرکت آزمایشی پایلوت')
        cls.staff = get_user_model().objects.create_superuser(
            username='pilot-v213-admin', email='staff@example.invalid', password='test-only')
        cls.nonstaff = get_user_model().objects.create_user(
            username='pilot-v213-member', password='test-only')
        cls.staff_without_permissions = get_user_model().objects.create_user(
            username='pilot-v213-staff-no-access', password='test-only', is_staff=True)
        cls.exp = PublicExperience.objects.create(
            company=cls.company, source_url='https://example.invalid/pilot-v213/experience',
            source_kind='work', title='تجربه خصوصی', body=STORY,
            content_sha256=hashlib.sha256(STORY.encode('utf-8')).hexdigest(),
            copyright_review='pending', company_attribution_status='unverified',
            independence_status='unknown')
        source_story = story_from_experience(cls.exp)
        cls.analysis = CriteriaAnalysis.objects.create(
            experience=cls.exp, criteria_version=version_for('work'),
            source_content_sha256=cls.exp.content_sha256,
            model_name='gpt-6-assistant-private-pilot',
            prompt_version='jobiew_assistant_annotation_v212',
            run_id='pilotv212_'+'a'*64, review_status='pilot_unverified',
            raw_payload={'engine':ENGINE, 'case_id':'work-001',
                         'story_sha256':story_digest(source_story),
                         'human_reference':'NOT_INDEPENDENT'})
        for i,axis in enumerate(axes_for('work')):
            score=2 if i==0 else None
            CriteriaAxisScore.objects.create(
                analysis=cls.analysis, key=axis.key, score=score,
                confidence=90 if score else 0,
                evidence=[EVIDENCE] if score else [],
                explanation='تأخیر مکرر در پرداخت گزارش شده است' if score else
                            'برای این معیار شاهد مشخصی در متن وجود ندارد',
                semantic_status='unreviewed')
        # A non-pilot result must remain invisible even to authorized staff.
        cls.other = CriteriaAnalysis.objects.create(
            experience=cls.exp, criteria_version=version_for('work'),
            source_content_sha256=cls.exp.content_sha256,
            model_name='other', prompt_version='other', run_id='other-v213',
            review_status='unreviewed', raw_payload={'engine':'other'})

    def index_url(self):
        return reverse('dual-pilot-dashboard-v213')

    def detail_url(self):
        return reverse('dual-pilot-detail-v213', args=[self.analysis.pk])

    def test_disabled_by_default_even_for_superuser(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', {'JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED':'0'}):
            self.assertEqual(self.client.get(self.index_url()).status_code,404)
            self.assertEqual(self.client.get(self.detail_url()).status_code,404)

    @override_settings(DEBUG=False)
    def test_closed_outside_debug(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(self.index_url()).status_code,404)

    def test_publication_enabled_closes_private_dashboard(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', {**FLAGS,'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1'}):
            self.assertEqual(self.client.get(self.index_url()).status_code,404)

    def test_anonymous_and_unprivileged_staff_denied(self):
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(self.index_url()).status_code,403)
            self.client.force_login(self.nonstaff)
            self.assertEqual(self.client.get(self.detail_url()).status_code,403)
            self.client.force_login(self.staff_without_permissions)
            self.assertEqual(self.client.get(self.index_url()).status_code,403)

    def test_private_summary_and_headers(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            response=self.client.get(self.index_url())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['summary']['cases'],1)
        self.assertEqual(response.context['summary']['numeric'],1)
        self.assertEqual(response.context['summary']['abstentions'],5)
        self.assertContains(response,'work-001')
        self.assertNotContains(response,'other-v213')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('noindex', response['X-Robots-Tag'])
        self.assertEqual(response['Referrer-Policy'],'no-referrer')

    def test_filters_and_bad_input(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(self.index_url(),{'kind':'interview'}).context['summary']['cases'],0)
            self.assertEqual(self.client.get(self.index_url(),{'kind':'work','company':self.company.pk}).context['summary']['cases'],1)
            self.assertEqual(self.client.get(self.index_url(),{'company':'other-company'}).context['summary']['cases'],0)
            self.assertEqual(self.client.get(self.index_url(),{'kind':'other'}).status_code,400)
            self.assertEqual(self.client.get(self.index_url(),{'company':'../escape'}).status_code,400)

    def test_detail_shows_exact_evidence_and_nulls(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            response=self.client.get(self.detail_url())
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['integrity_ok'])
        self.assertContains(response,EVIDENCE)
        self.assertContains(response,'فاقد نمره (null)',count=5)
        self.assertContains(response,'پیشنهاد آزمایشی')
        self.assertNotContains(response,'ثبت نهایی تصمیم')

    def test_stale_source_is_flagged_and_story_hidden(self):
        self.client.force_login(self.staff)
        PublicExperience.objects.filter(pk=self.exp.pk).update(content_sha256='b'*64)
        with patch.dict('os.environ', FLAGS):
            response=self.client.get(self.detail_url())
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.context['integrity_ok'])
        self.assertNotContains(response, STORY)
        self.assertContains(response,'قابل استناد نیست')

    def test_blocked_source_is_flagged(self):
        self.client.force_login(self.staff)
        PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='blocked')
        with patch.dict('os.environ', FLAGS):
            response=self.client.get(self.detail_url())
        self.assertFalse(response.context['integrity_ok'])

    def test_nonpilot_detail_never_accessible(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(reverse('dual-pilot-detail-v213',args=[self.other.pk])).status_code,404)

    def test_views_never_write_or_approve(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            self.client.get(self.index_url())
            self.client.get(self.detail_url())
            self.assertEqual(self.client.post(self.detail_url()).status_code,405)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.review_status,'pilot_unverified')
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(),0)
        self.assertFalse(CriteriaAxisScore.objects.filter(semantic_status='approved').exists())

    def test_public_company_page_never_leaks_pilot(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            response=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,EVIDENCE)
        self.assertNotContains(response,'work-001')
