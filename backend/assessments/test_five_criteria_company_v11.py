"""Django tests for private only five-point previews."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension
from assessments.five_criteria_company_v7 import build_company_research_preview
from companies.models import Company
from experiences.models import PublicExperience


class StaffV11PreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(id='v11company',source_url='https://example.net/c/11',source_name='v11',display_name='مجموعه پژوهشی')
        cls.staff=get_user_model().objects.create_superuser(username='v11_staff',password='test-only',email='v11@example.net')
        for n in range(1,6):
            e=PublicExperience.objects.create(company=cls.company,source_url=f'https://example.net/r/v11/{n}',source_kind='work',title='test',body='محتوای خصوصی؛ نباید در HTML عمومی باشد',content_sha256=str(n)*64)
            a=AiAssessment.objects.create(experience=e,criteria_version='five_v1',model_name='v11',prompt_version='v11',run_id=f'v11-{n}',publish_approved=False)
            for key in ('work_conditions_pressure','management_environment','growth_development','compensation_appreciation','stability_security'):
                AiDimension.objects.create(assessment=a,key=key,score=6,confidence=50,evidence=[{'quote':'شاهد','field':'body'}])
        cls.url=reverse('company-five-criteria-private-preview',args=[cls.company.pk])

    def test_private_preview_shows_provisional_not_public_score(self):
        data=build_company_research_preview(self.company)
        self.assertEqual(data['unique_experiences_in_scope'],5)
        self.assertTrue(data['provisional_profile_available'])
        for d in data['criteria']:
            self.assertEqual(d['mean_provisional'],6)
            self.assertEqual(d['n_provisional_used'],5)
            self.assertIsNone(d['score'])
        self.client.force_login(self.staff)
        html=self.client.get(self.url)
        self.assertEqual(html.status_code,200)
        self.assertContains(html,'mean_provisional')
        self.assertIn('no-store',html['Cache-Control'])
        self.assertNotContains(html,'محتوای خصوصی؛ نباید در HTML عمومی باشد')

    def test_public_preview_does_not_leak(self):
        public=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertEqual(public.status_code,200)
        self.assertNotContains(public,'mean_provisional')
        self.assertNotContains(public,'محتوای خصوصی؛ نباید در HTML عمومی باشد')
        self.assertEqual(self.client.get(self.url).status_code,403)
