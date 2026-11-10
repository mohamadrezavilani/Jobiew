"""Django regression tests: a safe direct route from each work experience to Claude.
No API requests, no paid model calls, and no production DB writes.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from assessments.models import AiAssessment
from companies.models import Company
from experiences.models import PublicExperience


class ClaudeShortcutCompatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username='shortcut-1121-root', email='test@example.invalid', password='test-only')
        cls.company = Company.objects.create(id='shortcut-1121-company',
            source_url='https://example.invalid/co', source_name='Test', display_name='شرکت نمونه')
        cls.work = PublicExperience.objects.create(company=cls.company,
            source_kind='work', title='متن تجربه', body='کار واقعی',
            source_url='https://example.invalid/exp', content_sha256='a'*64)
        cls.interview = PublicExperience.objects.create(company=cls.company,
            source_kind='interview', title='مصاحبه', body='مصاحبه استخدامی',
            source_url='https://example.invalid/interview', content_sha256='b'*64)
        cls.work_eval = AiAssessment.objects.create(experience=cls.work,
            criteria_version='five_v1', model_name='current', prompt_version='test', run_id='shortcut-1121-current')
        cls.interview_eval = AiAssessment.objects.create(experience=cls.interview,
            criteria_version='five_v1', model_name='incorrect-interview', prompt_version='test', run_id='shortcut-1121-interview')
        AiAssessment.objects.create(experience=cls.work,
            criteria_version='legacy9', model_name='legacy', prompt_version='test', run_id='shortcut-1121-old')

    def setUp(self):
        self.client.force_login(self.superuser)

    def detail(self, exp):
        return reverse('admin:companies_company_experience_detail', args=[self.company.pk, exp.pk])

    def test_historical_five_axis_claude_links_not_misrepresented_as_current(self):
        response = self.client.get(self.detail(self.work))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'صحت‌سنجی با Claude و مقایسهٔ پنج شاخص')
        self.assertNotContains(response, reverse(
            'admin:assessments_aiassessment_claude_detail',
            args=[self.work_eval.pk]))
        self.assertContains(response, 'هنوز تحلیل GPT-6 برای این تجربه ثبت نشده است')
        from assessments.claude_validation_models_v111 import ClaudeValidationRun
        self.assertEqual(ClaudeValidationRun.objects.count(), 0)

    def test_interview_five_axis_legacy_does_not_enable_paid_six_axis_call(self):
        response = self.client.get(self.detail(self.interview))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'صحت‌سنجی با Claude و مقایسهٔ پنج شاخص')

    def test_unprivileged_staff_never_see_link(self):
        staff = get_user_model().objects.create_user(username='shortcut-1121-staff',
            is_staff=True, password='not-used')
        for app, code in [('companies','view_company'),('experiences','view_publicexperience')]:
            staff.user_permissions.add(Permission.objects.get(content_type__app_label=app,codename=code))
        client = Client();client.force_login(staff)
        response = client.get(self.detail(self.work))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'صحت‌سنجی با Claude و مقایسهٔ پنج شاخص')

    def test_admin_pages_have_shared_font(self):
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'jobiew_vazir_v110.css')
