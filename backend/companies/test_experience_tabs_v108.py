
"""Jobiew v1.0.8 - public work/interview browsing regressions."""
from django.test import TestCase
from django.urls import reverse
from companies.models import Company
from experiences.models import PublicExperience
from assessments.models import AiAssessment, AiDimension

class ExperienceTabsV108Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='v108testcompany', source_url='https://example.org/company/v108',
            source_name='test', display_name='شرکت نمونه ۱۰۸',
        )
        cls.other = Company.objects.create(
            id='v108othercompany', source_url='https://example.org/company/other108',
            source_name='test', display_name='شرکت دیگر',
        )
        for i in range(14):
            PublicExperience.objects.create(
                company=cls.company,
                source_url=f'https://example.org/interview/{i}',
                source_kind='interview', job_title='برنامه‌نویس' if i == 0 else 'طراح محصول',
                title='متن عنوان غیرعمومی', body='متن محرمانه تجربه مصاحبه',
                content_sha256=f'{i+1:064x}',
            )
        cls.work = PublicExperience.objects.create(
            company=cls.company, source_url='https://example.org/work/108',
            source_kind='work', job_title='مهندس داده', title='خصوصی',
            body='محتوای محرمانه کار', content_sha256='e'*64,
        )
        PublicExperience.objects.create(
            company=cls.other, source_url='https://example.org/interview/other',
            source_kind='interview', job_title='تجربه شرکت دیگر', title='خصوصی',
            body='نامحرمانه', content_sha256='f'*64,
        )
        PublicExperience.objects.create(
            company=cls.company, source_url='https://example.org/interview/blocked',
            source_kind='interview', job_title='مصاحبه ممنوع', title='خصوصی',
            body='متن ممنوع', copyright_review='blocked', content_sha256='a'*64,
        )
        PublicExperience.objects.create(
            company=cls.company, source_url='https://example.org/interview/duplicate',
            source_kind='interview', job_title='مصاحبه تکراری', title='خصوصی',
            body='متن تکراری', independence_status='duplicate', content_sha256='b'*64,
        )
        PublicExperience.objects.create(
            company=cls.company, source_url='https://example.org/interview/rejected',
            source_kind='interview', job_title='مصاحبه انتساب رد', title='خصوصی',
            body='متن ردشده', company_attribution_status='rejected', content_sha256='c'*64,
        )
        # Interview AI must never be published in five-dimension UI.
        assessment = AiAssessment.objects.create(
            experience=PublicExperience.objects.filter(company=cls.company,source_kind='interview').first(),
            criteria_version='five_v1',model_name='test',prompt_version='v108',run_id='v108-interview',publish_approved=False,
        )
        AiDimension.objects.create(assessment=assessment,key='work_conditions_pressure',score=1,confidence=99,evidence=[])

    def url(self, tab='ai', **extras):
        from urllib.parse import urlencode
        params = {'tab':tab, **extras}
        return reverse('company-detail',args=[self.company.pk]) + '?' + urlencode(params)

    def test_interviews_have_own_tab_pagination_links_but_not_raw_text(self):
        resp=self.client.get(self.url('interview'))
        self.assertEqual(resp.status_code,200)
        self.assertContains(resp,'روایت‌های مصاحبه و فرایند استخدام')
        self.assertContains(resp,'14 مورد در آرشیو قابل نمایش')
        self.assertContains(resp,'صفحهٔ ۱ از ۲')
        self.assertContains(resp,'https://example.org/interview/')
        self.assertContains(resp,'مشاهده منشأ و دسترسی به روایت')
        self.assertNotContains(resp,'متن محرمانه تجربه مصاحبه')
        self.assertNotContains(resp,'متن عنوان غیرعمومی')
        self.assertNotContains(resp,'تجربه شرکت دیگر')
        self.assertNotContains(resp,'مصاحبه ممنوع')
        self.assertNotContains(resp,'مصاحبه تکراری')
        self.assertNotContains(resp,'مصاحبه انتساب رد')
        self.assertNotContains(resp,'data-chart-mode="published"')
        second=self.client.get(self.url('interview',page='2'))
        self.assertEqual(second.status_code,200)
        self.assertContains(second,'صفحهٔ ۲ از ۲')

    def test_filter_by_job_and_no_cross_company_or_kind_leaks(self):
        resp=self.client.get(self.url('interview',q='برنامه‌نویس'))
        self.assertContains(resp,'برنامه‌نویس')
        self.assertContains(resp,'https://example.org/interview/0')
        self.assertNotContains(resp,'https://example.org/interview/1')
        self.assertNotContains(resp,'مهندس داده')
        work=self.client.get(self.url('work'))
        self.assertContains(work,'مهندس داده')
        self.assertNotContains(work,'https://example.org/interview/0')
        self.assertNotContains(work,'محتوای محرمانه کار')

    def test_default_ai_tab_preserves_legacy_chart_and_no_provisional_scores(self):
        resp=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertEqual(resp.status_code,200)
        self.assertContains(resp,'data-chart-mode="empty"')
        self.assertContains(resp,'تحلیل محیط کار')
        self.assertNotContains(resp,'محتوای محرمانه کار')
        self.assertNotContains(resp,'متن محرمانه تجربه مصاحبه')
        resp=self.client.get(self.url('garbage'))
        self.assertEqual(resp.status_code,200)
        self.assertContains(resp,'data-chart-mode="empty"')

    def test_invalid_page_number_and_search_are_safe(self):
        resp=self.client.get(self.url('interview',page='not-a-page',q='<script>alert(1)</script>'))
        self.assertEqual(resp.status_code,200)
        self.assertNotContains(resp,'<script>alert(1)</script>')
