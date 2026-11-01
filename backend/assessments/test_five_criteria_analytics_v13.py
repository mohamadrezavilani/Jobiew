"""Integration tests for v13 private diagnostic dashboard and CSV export."""
import csv
import tempfile
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from assessments.five_criteria_analysis_v13 import analyze_provisional_criteria
from assessments.models import AiAssessment,AiDimension
from companies.models import Company
from experiences.models import PublicExperience


class CompanyInsightTests(SimpleTestCase):
    def test_strength_weakness_and_missing(self):
        rows=[{'key':'work_conditions_pressure','mean_provisional':8,'n_provisional_used':2},
              {'key':'management_environment','mean_provisional':4,'n_provisional_used':1},
              {'key':'growth_development','mean_provisional':None,'n_provisional_used':0}]
        s=analyze_provisional_criteria(rows)
        self.assertEqual(s['available_count'],2)
        self.assertEqual(s['total_scored_observations'],3)
        self.assertEqual(s['strengths'],['تعادل کار و زندگی و تناسب حجم کار'])
        self.assertEqual(s['weaknesses'],['کیفیت مدیریت و محیط کاری'])

    def test_equal_means_not_invented_strength(self):
        rows=[{'key':'work_conditions_pressure','mean_provisional':6,'n_provisional_used':1},
              {'key':'management_environment','mean_provisional':6,'n_provisional_used':1}]
        s=analyze_provisional_criteria(rows)
        self.assertTrue(s['all_equal'])
        self.assertFalse(s['strengths'])


class StaffAnalyticsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(id='v13-company',source_url='https://example.net/v13',
            source_name='v13',display_name='شرکت تحلیلی الف')
        cls.staff=get_user_model().objects.create_superuser('v13_superuser',
            'v13@example.net','test-only')
        for idx,score in enumerate((8,4),1):
            exp=PublicExperience.objects.create(company=cls.company,source_kind='work',
                source_url=f'https://example.net/v13/exp/{idx}',title='test',
                body='متن محرمانه گزارش',content_sha256=str(idx)*64)
            assessment=AiAssessment.objects.create(experience=exp,criteria_version='five_v1',
                model_name='v13',prompt_version='v13',run_id=f'v13-{idx}')
            AiDimension.objects.create(assessment=assessment,key='work_conditions_pressure',score=score,
                evidence=[{'quote':'شاهد محرمانه','field':'body'}])
            AiDimension.objects.create(assessment=assessment,key='management_environment',score=None)
        cls.url=reverse('company-five-criteria-private-analytics')

    def test_staff_only_no_raw_text_and_private_headers(self):
        self.assertEqual(self.client.get(self.url).status_code,403)
        user=get_user_model().objects.create_user('v13_limited','limited@example.net','pass')
        user.is_staff=True;user.save(update_fields=['is_staff'])
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.force_login(self.staff)
        response=self.client.get(self.url,{'q':'تحلیلی'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'شرکت تحلیلی الف')
        self.assertEqual(response.context['entries'][0]['preview']['criteria'][0]['mean_provisional'],6)
        self.assertNotContains(response,'متن محرمانه گزارش')
        self.assertNotContains(response,'شاهد محرمانه')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn('noindex',response['X-Robots-Tag'])

    def test_no_synthetic_score_for_abstention(self):
        self.client.force_login(self.staff)
        response=self.client.get(self.url)
        criteria=response.context['entries'][0]['preview']['criteria']
        self.assertIsNone(criteria[1]['mean_provisional'])
        self.assertFalse(response.context['entries'][0]['analysis']['strengths'])

    def test_csv_export_works_without_publication(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'export.csv'
            call_command('export_five_criteria_company_analysis_v13','--output',str(path))
            with path.open(encoding='utf-8-sig',newline='') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1)
            self.assertEqual(float(rows[0]['work_conditions_pressure_mean']),6.0)
            self.assertEqual(rows[0]['management_environment_mean'],'')
            self.assertEqual(rows[0]['publication_status'],'NOT_APPROVED_FOR_PUBLICATION')
