"""Reversible feature flag for the public homepage; synthetic metadata only."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from criteria_v2.models import CriteriaAnalysis
from experiences.models import PublicExperience


@override_settings(DEBUG=True)
class HomepagePublicCutoverV220Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='home-v220-company', display_name='شرکت کاندید صفحه اول',
            source_name='آرشیو', source_url='https://example.test/hp220',
            source_work_count=99,
        )
        cls.other = Company.objects.create(
            id='home-v220-other', display_name='شرکت دیگر',
            source_name='آرشیو', source_url='https://example.test/hp220-other',
        )
        exp = PublicExperience.objects.create(
            company=cls.company, source_url='https://example.test/hp220-e1',
            source_kind='work', title='PRIVATE_TITLE_220',
            body='PRIVATE_BODY_220', content_sha256='a' * 64,
        )
        PublicExperience.objects.create(
            company=cls.company, source_url='https://example.test/hp220-blocked',
            source_kind='work', title='PRIVATE_BLOCKED_220',
            content_sha256='b' * 64, copyright_review='blocked',
        )
        CriteriaAnalysis.objects.create(
            experience=exp, criteria_version='work6_v2', source_content_sha256='a' * 64,
            model_name='synthetic-private', prompt_version='v220-test',
            run_id='private-v220-run', review_status='pilot_unverified',
            raw_payload={'PRIVATE_SCORE_220': 9},
        )

    def test_default_off_preserves_existing_index_and_urls(self):
        with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_ENABLED': '0'}):
            old = self.client.get(reverse('company-index'))
            directory = self.client.get(reverse('company-directory'))
            details = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(old.status_code, 200)
        self.assertTemplateUsed(old, 'companies/index.html')
        self.assertTemplateUsed(directory, 'companies/index.html')
        self.assertEqual(details.status_code, 200)
        self.assertContains(old, 'تجربه کاری شرکت‌ها')
        self.assertNotContains(old, 'homepage_preview_v219.js')

    def test_public_cutover_flag_is_exact_value_only(self):
        for value in ('', 'true', 'yes', '01', '1 '):
            with self.subTest(value=value), patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_ENABLED': value}):
                response = self.client.get(reverse('company-index'))
                self.assertTemplateUsed(response, 'companies/index.html')

    def test_enabled_public_home_is_anonymous_metadata_only_and_noindex(self):
        with patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_PUBLIC_ENABLED': '1',
            'JOBIEW_HOMEPAGE_PREVIEW_ENABLED': '0',
        }):
            home = self.client.get(reverse('company-index'))
            directory = self.client.get(reverse('company-directory'))
            gated_preview = self.client.get(reverse('homepage-preview-v219'))
        self.assertEqual(home.status_code, 200)
        self.assertTemplateUsed(home, 'companies/homepage_preview_v219.html')
        self.assertTemplateUsed(directory, 'companies/index.html')
        self.assertEqual(gated_preview.status_code, 404)
        self.assertContains(home, 'شرکت کاندید صفحه اول')
        self.assertContains(home, '۱ تجربهٔ کاری')
        self.assertContains(home, 'امتیاز موجود نیست')
        self.assertNotContains(home, 'پیش‌نمایش خصوصی')
        for sentinel in ('PRIVATE_TITLE_220', 'PRIVATE_BODY_220', 'PRIVATE_BLOCKED_220',
                         'PRIVATE_SCORE_220', 'private-v220-run', 'source_work_count',
                         '99 تجربه'):
            self.assertNotContains(home, sentinel)
        self.assertEqual(home['X-Robots-Tag'], 'noindex, noarchive')
        self.assertIn('no-store', home['Cache-Control'])
        self.assertEqual(home['Referrer-Policy'], 'no-referrer')
        self.assertIn("object-src 'none'", home['Content-Security-Policy'])
        self.assertNotContains(home, 'action="/internal/homepage-preview/"')
        self.assertContains(home, 'action="/"')

    def test_public_mode_and_filters_preserve_directories_and_types(self):
        with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_ENABLED': '1'}):
            home = self.client.get(reverse('company-index'), {'q': 'کاندید', 'has_records': '1'})
            interview = self.client.get(reverse('company-index'), {'mode': 'interview', 'has_records': '1'})
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home.context['page'].paginator.count, 1)
        self.assertEqual(home.context['page'].object_list[0].experience_count, 1)
        self.assertEqual(interview.context['page'].paginator.count, 0)
        self.assertContains(home, '/companies/')
        self.assertNotContains(home, 'PRIVATE_TITLE_220')

    def test_public_mode_escapes_malicious_company_and_query_text(self):
        Company.objects.create(
            id='home-v220-xss', source_name='test',
            source_url='https://example.test/hp220-xss',
            display_name='<img src=x onerror=alert(42)>',
        )
        with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_ENABLED': '1'}):
            page = self.client.get(reverse('company-index'), {'q': '<img'})
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'<img src=x onerror=alert(42)>', page.content)
        self.assertIn(b'&lt;img', page.content)
        self.assertIn(b'onerror=alert(42)', page.content)

    def test_post_does_not_enter_new_public_handler(self):
        with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_ENABLED': '1'}):
            response = self.client.post(reverse('company-index'), data={})
        self.assertEqual(response.status_code, 405)
