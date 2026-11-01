"""V12 comparison regression checks, including no public exposure."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension
from companies.models import Company
from experiences.models import PublicExperience


class FiveCriteriaComparisonV12Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Company.objects.create(id='v12-a', source_url='https://example.net/company/a',
                                       source_name='A', display_name='مجموعه مقایسه الف')
        cls.b = Company.objects.create(id='v12-b', source_url='https://example.net/company/b',
                                       source_name='B', display_name='مجموعه مقایسه ب')
        cls.c = Company.objects.create(id='v12-c', source_url='https://example.net/company/c',
                                       source_name='C', display_name='مجموعه بدون داده')
        cls.staff = get_user_model().objects.create_superuser('compare_v12_staff', 'compare@example.net', 'test-only')
        for company,score in [(cls.a,8),(cls.b,4)]:
            e = PublicExperience.objects.create(company=company,
                source_url=f'https://example.net/experience/{company.pk}', source_kind='work',
                title='محرمانه', body='بدنه محرمانه که نباید وارد HTML شود',
                content_sha256=(company.pk+'X'*64)[:64])
            assessment = AiAssessment.objects.create(experience=e,criteria_version='five_v1',
                model_name='v12-test',prompt_version='test',run_id='v12-'+company.pk)
            AiDimension.objects.create(assessment=assessment,key='work_conditions_pressure',
                                      score=score,confidence=55,evidence=[{'quote':'متن محرمانه شاهد','field':'body'}])
            AiDimension.objects.create(assessment=assessment,key='management_environment',
                                      score=None,confidence=0)
        cls.url = reverse('company-five-criteria-private-compare')

    def test_unauthenticated_and_unprivileged_denied(self):
        self.assertEqual(self.client.get(self.url).status_code,403)
        limited = get_user_model().objects.create_user(username='compare_limited',password='test-only')
        limited.is_staff=True
        limited.save(update_fields=['is_staff'])
        self.client.force_login(limited)
        self.assertEqual(self.client.get(self.url).status_code,403)

    def test_staff_search_select_and_private_headers(self):
        self.client.force_login(self.staff)
        result=self.client.get(self.url, {'q':'مقایسه'})
        self.assertEqual(result.status_code,200)
        self.assertContains(result,'مجموعه مقایسه الف')
        self.assertContains(result,'مجموعه مقایسه ب')
        self.assertIn('no-store',result['Cache-Control'])
        self.assertIn('noindex',result['X-Robots-Tag'])

    def test_two_companies_with_partial_scores(self):
        self.client.force_login(self.staff)
        response=self.client.get(self.url,{'company':[self.a.pk,self.b.pk]})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'company-compare-v12-data')
        self.assertContains(response,'8 / ۱۰')
        self.assertContains(response,'4 / ۱۰')
        self.assertNotContains(response,'بدنه محرمانه که نباید وارد HTML شود')
        self.assertNotContains(response,'متن محرمانه شاهد')
        self.assertEqual(len(response.context['entries']),2)
        self.assertEqual(response.context['matrix'][0]['cells'][0]['score'],8)
        self.assertEqual(response.context['matrix'][0]['cells'][1]['score'],4)
        self.assertIsNone(response.context['matrix'][1]['cells'][0]['score'])

    def test_one_company_and_missing_data_are_not_invented(self):
        self.client.force_login(self.staff)
        response=self.client.get(self.url,{'company':[self.a.pk]})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.context['ready'])
        response=self.client.get(self.url,{'company':[self.a.pk,self.c.pk]})
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.context['matrix'][0]['cells'][1]['score'])

    def test_too_many_unknown_and_duplicate_ids_are_rejected(self):
        self.client.force_login(self.staff)
        cases=[{'company':['a','b','c','d','e','f']},
               {'company':[self.a.pk,self.a.pk]},
               {'company':['unknown',self.a.pk]}]
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(self.client.get(self.url,args).status_code,400)

    def test_public_company_detail_unaffected(self):
        response=self.client.get(reverse('company-detail',args=[self.a.pk]))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'company-compare-v12-data')
        self.assertNotContains(response,'متن محرمانه شاهد')
