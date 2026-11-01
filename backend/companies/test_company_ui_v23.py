"""Smoke and privacy tests for the v23 presentation-only refresh."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from companies.models import Company
from assessments.models import AiAssessment, AiDimension
from experiences.models import PublicExperience


class CompanyUIV23Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='company-ui-v23-test', source_url='https://example.org/c/ui-v23',
            source_name='Example', display_name='شرکت تست رابط کاربری',
        )
        cls.staff = get_user_model().objects.create_superuser(
            username='ui_v23_staff', email='ui-v23@example.org', password='test-only-do-not-use'
        )
        for index in range(3):
            exp = PublicExperience.objects.create(
                company=cls.company, source_url=f'https://example.org/e/ui23/{index}',
                source_kind='work', title='عنوان خصوصی',
                body='متن خصوصی نمونه نباید در HTML عمومی یا داخلی نمایش داده شود',
                content_sha256=str(index + 1) * 64,
            )
            assessment = AiAssessment.objects.create(
                experience=exp, criteria_version='five_v1', model_name='ui-v23-test',
                prompt_version='ui-v23', run_id=f'ui-v23-{index}',
                publish_approved=False,
            )
            AiDimension.objects.create(
                assessment=assessment, key='work_conditions_pressure',
                score=5 + index, confidence=60, evidence=[{'quote':'محرمانه', 'field':'body'}],
            )

    def test_public_page_is_responsive_and_has_no_provisional_score(self):
        response = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'company_profile_v23.css')
        self.assertContains(response, 'data-profile-kind="public"')
        self.assertContains(response, 'تعادل کار و زندگی')
        self.assertNotContains(response, 'wi-criteria-v23-data')
        self.assertNotContains(response, 'mean_provisional')
        self.assertNotContains(response, 'متن خصوصی نمونه')

    def test_internal_preview_is_staff_only_and_noindex(self):
        url = reverse('company-five-criteria-private-preview', args=[self.company.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-profile-kind="staff"')
        self.assertContains(response, 'wi-criteria-v23-data')
        self.assertContains(response, 'mean_provisional')
        self.assertContains(response, 'غیرقابل انتشار')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('noindex', response['X-Robots-Tag'])
        self.assertNotContains(response, 'متن خصوصی نمونه')

    def test_public_radar_is_only_an_empty_scaffold(self):
        response = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertContains(response, 'data-chart-mode="empty"')
        self.assertNotContains(response, 'data-chart-mode="provisional"')
        self.assertNotContains(response, 'نمودار آبی')
