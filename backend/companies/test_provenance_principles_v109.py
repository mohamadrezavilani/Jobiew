"""Public trust, provenance and privacy invariants for Jobiew v1.0.9."""
from django.test import TestCase
from django.urls import reverse
from companies.models import Company
from experiences.models import PublicExperience
from companies.views import _public_job_title, _safe_source_url


class ProvenancePrinciplesV109Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='v109company', source_url='https://example.org/company/v109',
            source_name='third-party', display_name='شرکت تست ۱۰۹',
            source_work_count=999, source_interview_count=999,
        )
        cls.interview = PublicExperience.objects.create(
            company=cls.company, source_kind='interview',
            source_url='https://example.org/interviews/109', source_site='external.example',
            job_title='مهندس نرم‌افزار', title='متن عنوان واقعی نباید نمایش داده شود',
            body='متن کامل خصوصی مصاحبه', content_sha256='1'*64,
        )
        cls.work = PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.org/work/109', source_site='external.example',
            job_title='کارشناس فنی', title='عنوان محرمانه',
            body='متن کامل خصوصی کاری', content_sha256='2'*64,
        )
        PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.org/work/blocked', copyright_review='blocked',
            job_title='گزارش ممنوعه', title='خصوصی', content_sha256='3'*64,
        )

    def url(self, tab='ai', **query):
        from urllib.parse import urlencode
        return reverse('company-detail', args=[self.company.pk])+'?'+urlencode({'tab': tab, **query})

    def test_ai_is_default_and_not_just_external_link_directory(self):
        r = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'تحلیل محیط کار')
        self.assertContains(r, 'work6_v2')
        self.assertContains(r, 'interview6_v2')
        self.assertContains(r, 'در انتظار بازبینی مجدد تجربه‌ها')
        self.assertContains(r, 'data-chart-mode="empty"')
        self.assertNotContains(r, 'متن کامل خصوصی')
        self.assertNotContains(r, 'external.example')

    def test_interview_card_has_optional_attribution_without_raw_body(self):
        r = self.client.get(self.url('interview'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'مهندس نرم‌افزار')
        self.assertContains(r, '<summary>مشاهده منشأ و دسترسی به روایت</summary>', html=True)
        self.assertContains(r, 'external.example')
        self.assertContains(r, 'https://example.org/interviews/109')
        self.assertContains(r, 'این بخش برای آشنایی با تجربهٔ متقاضیان استخدام است')
        self.assertNotContains(r, 'متن کامل خصوصی مصاحبه')
        self.assertNotContains(r, 'متن عنوان واقعی نباید نمایش داده شود')
        self.assertNotContains(r, 'https://example.org/work/109')

    def test_counts_represent_visible_archive_not_source_estimates(self):
        r = self.client.get(self.url('work'))
        self.assertContains(r, '1 مورد در آرشیو قابل نمایش')
        self.assertContains(r, '1</strong><span>تجربه کاری فهرست‌شده')
        self.assertNotContains(r, '999</strong><span>تجربه کاری ثبت‌شده')
        self.assertNotContains(r, 'گزارش ممنوعه')

    def test_title_search_does_not_become_oracle_on_private_source_title(self):
        r = self.client.get(self.url('interview', q='متن عنوان واقعی'))
        self.assertContains(r, 'برای این عنوان شغلی موردی پیدا نشد')
        self.assertNotContains(r, 'https://example.org/interviews/109')
        r2 = self.client.get(self.url('interview', q='نرم‌افزار'))
        self.assertContains(r2, 'مهندس نرم‌افزار')

    def test_obvious_private_contacts_are_never_labels(self):
        self.assertEqual(_public_job_title('someone@example.org'), 'عنوان شغلی ثبت نشده')
        self.assertEqual(_public_job_title('مهندس 09121234567'), 'عنوان شغلی ثبت نشده')
        self.assertEqual(_public_job_title('مهندس نرم‌افزار'), 'مهندس نرم‌افزار')
        self.assertIsNone(_safe_source_url('javascript:alert(1)'))
        self.assertIsNone(_safe_source_url('https://user:secret@example.org/private'))
        self.assertEqual(_safe_source_url('https://example.org/interviews/109'), 'https://example.org/interviews/109')
