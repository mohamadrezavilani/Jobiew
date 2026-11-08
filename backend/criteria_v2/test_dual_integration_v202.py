"""V2 integration regressions for archived/private and independent public UI.

No online dependencies, paid requests, rescoring or writes to historical data.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from companies.models import Company
from experiences.models import PublicExperience
from assessments.models import AiAssessment
from voting.services import VoteDenied, validate_scores


class DualV202IntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(id='dual-v202', source_url='https://example.test/company',
            source_name='Test', display_name='شرکت بازبینی ۲۰۲')
        cls.exp = PublicExperience.objects.create(company=cls.company, source_kind='work',
            source_url='https://example.test/experience', title='private title',
            body='private body must never leak', content_sha256='d'*64)
        cls.ai = AiAssessment.objects.create(experience=cls.exp, criteria_version='five_v1',
            model_name='archived', prompt_version='archived', run_id='dual-v202-old',
            publish_approved=True)
        cls.staff = get_user_model().objects.create_superuser(
            username='dual-v202-staff', email='v202@example.invalid', password='test-only')

    def test_public_two_groups_never_expose_legacy_score_or_private_body(self):
        res = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'work6_v2')
        self.assertContains(res, 'interview6_v2')
        self.assertContains(res, 'data-chart-mode="empty"', count=2)
        self.assertNotContains(res, 'private body must never leak')
        self.assertNotContains(res, 'wi-criteria-v23-data')
        self.assertNotContains(res, 'data-chart-mode="published"')

    def test_legacy_staff_preview_is_private_and_archived(self):
        url = reverse('company-five-criteria-private-preview', args=[self.company.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.staff)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'آرشیو پژوهشی پنج‌معیاری')
        self.assertIn('no-store', res['Cache-Control'])
        self.assertIn('noindex', res['X-Robots-Tag'])
        self.assertEqual(res['X-Jobiew-Criteria-Archive'], 'five_v1-read-only')

    def test_historical_comparison_validates_arguments(self):
        self.client.force_login(self.staff)
        url = reverse('company-five-criteria-private-compare')
        res = self.client.get(url, {'company': ['fake', self.company.pk]})
        self.assertEqual(res.status_code, 400)

    def test_old_five_voting_stays_blocked(self):
        with self.assertRaises(VoteDenied):
            validate_scores({'work_conditions_pressure': 7})

    def test_public_interview_pagination_remains_persian(self):
        for i in range(14):
            PublicExperience.objects.create(company=self.company, source_kind='interview',
                source_url=f'https://example.test/interviews/{i}', title='private',
                body='private body must never leak', content_sha256=f'{i + 1:064x}')
        url = reverse('company-detail', args=[self.company.pk]) + '?tab=interview'
        res = self.client.get(url)
        self.assertContains(res, 'صفحهٔ ۱ از ۲')
        self.assertNotContains(res, 'private body must never leak')
