"""v2.0.27: 6+6 is the only active per-experience admin scoring workspace.

Historical five_v1 assessments must not enter the display or public output.
All sources, model scores and privacy constraints are synthetic.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from assessments.models import AiAssessment, AiDimension
from companies.models import Company
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import CriteriaAnalysis, CriteriaScoreReviewEvent
from criteria_v2.registry import axes_for
from experiences.models import PublicExperience

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
    'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '0',
}
WORK_BODY = ('در شرکت حقوق ماهانه با تأخیر پرداخت می‌شد و اضافه‌کاری زیاد بود. '
             'دربارهٔ سایر زمینه‌ها تجربهٔ قابل اعتمادی ندارم.')
INTERVIEW_BODY = ('مصاحبه‌کننده با احترام برخورد کرد اما نتیجه را دیر اعلام کردند. '
                  'دربارهٔ دیگر معیارها شاهدی ندارم.')


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['jobiew.ir', 'testserver'],
                   CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class SixAxisAdminExperienceV227Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='v227-company', source_url='https://example.invalid/company/v227',
            source_name='synthetic', display_name='شرکت نمایشی ۶+۶')
        cls.other = Company.objects.create(
            id='v227-other', source_url='https://example.invalid/company/other',
            source_name='synthetic', display_name='شرکت دیگر')
        cls.staff = get_user_model().objects.create_superuser(
            username='v227-manager', password='synthetic-not-real',
            email='manager-v227@example.invalid')
        cls.work = PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.invalid/work/v227',
            title='تجربه کاری', body=WORK_BODY, content_sha256='c'*64)
        cls.interview = PublicExperience.objects.create(
            company=cls.company, source_kind='interview',
            source_url='https://example.invalid/interview/v227',
            title='مصاحبه', body=INTERVIEW_BODY, content_sha256='d'*64)
        cls.unscored = PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.invalid/unscored/v227',
            title='هنوز پردازش‌نشده', body='بدون پیشنهاد عددی',
            content_sha256='e'*64)
        cls.foreign = PublicExperience.objects.create(
            company=cls.other, source_kind='work',
            source_url='https://example.invalid/foreign/v227',
            title='محرمانه شرکت دیگر', body='فقط برای شرکت دیگر',
            content_sha256='f'*64)
        for exp, quote in (
            (cls.work, 'حقوق ماهانه با تأخیر پرداخت می‌شد'),
            (cls.interview, 'مصاحبه‌کننده با احترام برخورد کرد'),
        ):
            axes = axes_for(exp.source_kind)
            dimensions = {
                axis.key: (
                    {'score': 4, 'confidence': 89, 'evidence': quote,
                     'explanation': 'این شاهد به معیار مورد بررسی مربوط است'}
                    if i == 0 else
                    {'score': None, 'confidence': 0, 'evidence': '',
                     'explanation': 'شاهد کافی برای این محور وجود ندارد'}
                ) for i, axis in enumerate(axes)
            }
            stage_one({
                'experience_id': exp.pk, 'company_id': exp.company_id,
                'kind': exp.source_kind,
                'source_content_sha256': exp.content_sha256,
                'story_sha256': story_digest(story_from_experience(exp)),
                'model_name': 'GPT-6-synthetic',
                'review_status': 'unverified_private_proposal',
                'prediction': {
                    'detected_kind': exp.source_kind, 'kind_confidence': 92,
                    'dimensions': dimensions,
                },
            })
        legacy = AiAssessment.objects.create(
            experience=cls.work, criteria_version='five_v1',
            model_name='ChatGPT-historical-only', prompt_version='five_v1',
            run_id='synthetic-old-five-axis')
        AiDimension.objects.create(
            assessment=legacy, key='management_environment', score=10,
            confidence=80, explanation='حمایت مدیر از متن پنج معیار قدیمی')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.staff)
        self.list_url = reverse('admin:companies_company_experiences',
                                args=[self.company.pk])

    def get(self, url, flags=None):
        with patch.dict('os.environ', FLAGS if flags is None else flags):
            return self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')

    def detail(self, exp):
        return reverse('admin:companies_company_experience_detail',
                       args=[self.company.pk, exp.pk])

    def test_work_six_axes_are_real_and_not_mixed_with_five_v1(self):
        response = self.get(self.detail(self.work))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ارزیابی ۶معیاری GPT-6')
        self.assertContains(response, 'حقوق ماهانه با تأخیر پرداخت می‌شد')
        self.assertContains(response, 'حقوق، مزایا و عدالت پرداخت')
        self.assertContains(response, 'چالش‌برانگیز بودن کار و اختیار عمل')
        self.assertNotContains(response, 'احترام و رفتار حرفه‌ای')
        self.assertNotContains(response, 'حمایت مدیر از متن پنج معیار قدیمی')
        self.assertNotContains(response, 'five_v1')
        self.assertNotContains(response, 'Claude')
        self.assertContains(response, 'پیشنهاد خصوصی GPT-6؛ هنوز تأیید نشده')
        self.assertEqual(len(response.context['six_axes']), 6)
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())

    def test_interview_shows_its_six_distinct_axes(self):
        response = self.get(self.detail(self.interview))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'احترام و رفتار حرفه‌ای')
        self.assertContains(response, 'نتیجه‌دهی و بازخورد')
        self.assertNotContains(response, 'حقوق، مزایا و عدالت پرداخت')
        self.assertEqual(len(response.context['six_axes']), 6)
        self.assertEqual(response.context['six_run'].criteria_version, 'interview6_v2')

    def test_no_checkpoint_is_not_backfilled_from_five_axis(self):
        response = self.get(self.detail(self.unscored))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'هنوز تحلیل GPT-6 برای این تجربه ثبت نشده')
        self.assertNotContains(response, 'five_v1')
        listing = self.get(self.list_url)
        self.assertContains(listing, 'هنوز در checkpoint پردازش نشده')
        self.assertContains(listing, 'نمره‌های ۶معیاری')
        self.assertNotContains(listing, 'حمایت مدیر از متن پنج معیار قدیمی')
        self.assertNotContains(listing, self.foreign.title)
        self.assertEqual(listing.context['page_obj'].paginator.count, 3)

    def test_ineligible_private_access_never_exposes_six_scores(self):
        flags = {**FLAGS, 'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '0'}
        response = self.get(self.detail(self.work), flags)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فقط برای بازبینِ مجاز')
        self.assertNotContains(response, 'چالش‌برانگیز بودن کار و اختیار عمل')
        self.assertNotContains(response, 'حمایت مدیر از متن پنج معیار قدیمی')
        self.assertFalse(response.context['can_view_six'])

    def test_tampered_source_blocks_all_six_scores(self):
        PublicExperience.objects.filter(pk=self.work.pk).update(
            content_sha256='0'*64)
        response = self.get(self.detail(self.work))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'نمایش امتیازها برای بررسی مجدد مسدود است')
        self.assertFalse(response.context['six_integrity_ok'])
        self.assertNotContains(response, 'چالش‌برانگیز بودن کار و اختیار عمل')

    def test_cross_company_and_staff_scope_are_enforced(self):
        self.assertEqual(self.get(self.detail(self.foreign)).status_code, 404)
        staff = get_user_model().objects.create_user(
            username='v227-limited', password='not-real', is_staff=True)
        staff.user_permissions.add(Permission.objects.get(
            content_type__app_label='companies', codename='view_company'))
        staff.user_permissions.add(Permission.objects.get(
            content_type__app_label='experiences', codename='view_publicexperience'))
        cl = Client()
        cl.force_login(staff)
        with patch.dict('os.environ', FLAGS):
            response = cl.get(self.detail(self.work), secure=True,
                              HTTP_HOST='jobiew.ir')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فقط برای بازبینِ مجاز')
        self.assertNotContains(response, 'حقوق، مزایا و عدالت پرداخت')
        self.assertNotContains(response, 'حمایت مدیر از متن پنج معیار قدیمی')

    def test_public_company_staff_shortcuts_are_current(self):
        response = self.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response,
            reverse('admin:companies_company_checkpoint_release',
                    args=[self.company.pk]))
        self.assertNotContains(response, 'five-criteria')
        self.assertNotContains(response, 'five_v1')
        self.assertNotContains(response, self.work.body)
