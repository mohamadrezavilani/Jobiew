"""Legacy Claude five-axis links stay archival; active UI uses separate six-axis only."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from assessments.models import AiAssessment
from companies.models import Company
from experiences.models import PublicExperience
from criteria_v2.models import ClaudeSixCheck


class ClaudeShortcutCompatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username='shortcut-1121-root', email='test@example.invalid',
            password='test-only')
        cls.company = Company.objects.create(
            id='shortcut-1121-company',
            source_url='https://example.invalid/co',
            source_name='Test', display_name='شرکت نمونه')
        cls.work = PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            title='متن تجربه', body='کار واقعی',
            source_url='https://example.invalid/exp',
            content_sha256='a'*64)
        cls.interview = PublicExperience.objects.create(
            company=cls.company, source_kind='interview',
            title='مصاحبه', body='مصاحبه استخدامی',
            source_url='https://example.invalid/interview',
            content_sha256='b'*64)
        cls.work_eval = AiAssessment.objects.create(
            experience=cls.work, criteria_version='five_v1',
            model_name='historical', prompt_version='test',
            run_id='shortcut-1121-historical')

    def setUp(self):
        self.client.force_login(self.superuser)

    def detail(self, exp):
        return reverse('admin:companies_company_experience_detail',
                       args=[self.company.pk, exp.pk])

    def test_historical_five_axis_claude_is_not_linked_from_active_detail(self):
        detail = self.client.get(self.detail(self.work))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, 'مقایسهٔ پنج شاخص')
        self.assertNotContains(detail, reverse(
            'admin:assessments_aiassessment_claude_detail',
            args=[self.work_eval.pk]))
        # Archival analysis remains accessible for audit; paid execution remains frozen.
        old = reverse('admin:assessments_aiassessment_claude_detail',
                      args=[self.work_eval.pk])
        self.assertEqual(self.client.get(old).status_code, 200)
        self.assertFalse(ClaudeSixCheck.objects.exists())

    def test_unscored_experience_has_no_six_axis_vendor_button(self):
        for exp in (self.work, self.interview):
            page = self.client.get(self.detail(exp))
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, 'بررسی شش‌معیاری با Claude')
            self.assertContains(page, 'هنوز تحلیل GPT-6')

    def test_unprivileged_staff_cannot_see_private_claude(self):
        staff = get_user_model().objects.create_user(
            username='shortcut-1121-staff', is_staff=True, password='not-used')
        for app, code in [('companies','view_company'),
                          ('experiences','view_publicexperience')]:
            staff.user_permissions.add(Permission.objects.get(
                content_type__app_label=app, codename=code))
        client = Client()
        client.force_login(staff)
        response = client.get(self.detail(self.work))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'بررسی شش‌معیاری با Claude')

    def test_admin_pages_have_shared_font(self):
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'jobiew_vazir_v110.css')
