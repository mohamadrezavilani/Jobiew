"""Company isolation, source gates and staff-only preview contract tests (Django)."""
import json
from io import StringIO
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from assessments.five_criteria_company_v7 import build_company_research_preview, research_aggregate_for_company
from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent
from companies.models import Company
from experiences.models import PublicExperience


class PrivateFiveCriteriaCompanyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='five-company-a', source_url='https://example.net/companies/a',
            source_name='A', display_name='شرکت آزمایشی الف', identity_status='verified')
        cls.other = Company.objects.create(
            id='five-company-b', source_url='https://example.net/companies/b',
            source_name='B', display_name='شرکت آزمایشی ب', identity_status='verified')
        cls.staff = get_user_model().objects.create_superuser(
            username='five_qa_staff', email='qa@example.net', password='only-for-unit-tests')
        cls.experiences = []
        for i in range(3):
            exp = PublicExperience.objects.create(
                company=cls.company, source_url=f'https://example.net/experience/{i}',
                source_kind='work', title='عنوان آزمایشی', body='متن محرمانه تست که نباید نمایش داده شود',
                content_sha256=(str(i) * 64), copyright_review='approved',
                company_attribution_status='verified', independence_status='verified')
            cls.experiences.append(exp)
            assessment = AiAssessment.objects.create(
                experience=exp, criteria_version='five_v1', model_name='research-unit',
                prompt_version='v7', run_id=f'five-company-unit-{i}',
                independent_review_status='unreviewed', publish_approved=False)
            dim = AiDimension.objects.create(
                assessment=assessment, key='work_conditions_pressure',
                score=4+i*2, confidence=70, evidence=[{'quote':'شاهد تست','field':'body'}])
            AiHumanReviewEvent.objects.create(
                dimension=dim, reviewer=cls.staff, verdict='supported')
        cls.internal_path = reverse('company-five-criteria-private-preview', args=[cls.company.pk])

    def test_refuses_mixed_company_rows(self):
        row = dict(company_id='five-company-b', experience_id='10',
                   dimension='work_conditions_pressure', score=7,
                   human_verified=True, rights_verified=True,
                   attribution_verified=True, independence_verified=True)
        with self.assertRaises(ValueError):
            research_aggregate_for_company('five-company-a', [row])
        with self.assertRaises(ValueError):
            research_aggregate_for_company('', [])

    def test_private_preview_scoped_and_never_published(self):
        result = build_company_research_preview(self.company)
        self.assertEqual(result['company_id'], self.company.pk)
        criterion = result['criteria'][0]
        self.assertEqual(result['unique_experiences_in_scope'], 3)
        self.assertEqual(criterion['n_verified_independent'], 3)
        self.assertEqual(criterion['score'], 6)
        self.assertEqual(criterion['mean_ai_text_support_unvalidated'], 70.0)
        self.assertEqual(result['publication_status'], 'NOT_APPROVED_FOR_PUBLICATION')
        other = build_company_research_preview(self.other)
        self.assertEqual(other['unique_experiences_in_scope'], 0)
        self.assertIsNone(other['criteria'][0]['score'])

    def test_recent_unsupported_event_retracts_diagnostic(self):
        dim = AiDimension.objects.get(assessment__experience=self.experiences[0])
        AiHumanReviewEvent.objects.create(
            dimension=dim, reviewer=self.staff, verdict='unsupported',
            primary_error='unsupported_score', note='امتیاز با شاهد سازگار نیست و نباید در تجمیع باشد')
        result = build_company_research_preview(self.company)
        self.assertEqual(result['criteria'][0]['n_verified_independent'], 2)
        self.assertIsNone(result['criteria'][0]['score'])

    def test_company_not_identity_verified_suppresses_even_internal_mean(self):
        Company.objects.filter(pk=self.company.pk).update(identity_status='unverified')
        self.company.refresh_from_db()
        result = build_company_research_preview(self.company)
        self.assertIsNone(result['criteria'][0]['score'])
        self.assertEqual(result['criteria'][0]['status'], 'COMPANY_IDENTITY_UNVERIFIED')

    def test_gates_block_unverified_rights(self):
        PublicExperience.objects.filter(pk=self.experiences[0].pk).update(copyright_review='pending')
        result = build_company_research_preview(self.company)
        self.assertEqual(result['criteria'][0]['n_verified_independent'], 2)
        self.assertIsNone(result['criteria'][0]['score'])

    def test_anonymous_cannot_access_internal_preview(self):
        response = self.client.get(self.internal_path)
        self.assertEqual(response.status_code, 403)

    def test_staff_preview_private_no_source_body_and_public_page_score_free(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.internal_path)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('noindex', response['X-Robots-Tag'])
        self.assertNotContains(response, 'متن محرمانه تست که نباید نمایش داده شود')
        self.assertContains(response, 'غیرقابل انتشار')
        self.client.logout()
        page = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, '6.0')
        self.assertNotContains(page, 'پیش‌نمایش داخلی پنج معیار')
        self.assertNotContains(page, 'متن محرمانه تست که نباید نمایش داده شود')

    def test_status_command_read_only_and_counts(self):
        out = StringIO()
        call_command('five_criteria_status_v7', stdout=out)
        result = json.loads(out.getvalue())
        self.assertEqual(result['assessments'], 3)
        self.assertEqual(result['unique_work_experiences'], 3)
        self.assertEqual(result['companies_in_scope'], 1)
        self.assertEqual(result['dimension_rows'], 3)
        self.assertEqual(result['provisional_scores'], 3)
        self.assertEqual(result['database_writes'], 0)

    def test_staff_without_specific_permissions_denied(self):
        limited = get_user_model().objects.create_user(
            username='limited_staff', password='tests-only')
        limited.is_staff = True
        limited.save(update_fields=['is_staff'])
        self.client.force_login(limited)
        response = self.client.get(self.internal_path)
        self.assertEqual(response.status_code, 403)
