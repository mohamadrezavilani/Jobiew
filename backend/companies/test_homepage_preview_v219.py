"""Private homepage design acceptance; never exercise real publication or paid models."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from criteria_v2.models import CriteriaAnalysis
from experiences.models import PublicExperience


@override_settings(DEBUG=True)
class HomepagePreviewV219Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Company.objects.create(
            id='home-v219-first', source_url='https://example.test/company/hp-first',
            source_name='archive', display_name='آزمون الف',
            source_work_count=14, source_interview_count=1,
        )
        cls.second = Company.objects.create(
            id='home-v219-second', source_url='https://example.test/company/hp-second',
            source_name='archive', display_name='آزمون ب',
            source_work_count=2, source_interview_count=15,
            identity_status='verified', tech_status='verified', tehran_status='verified',
        )
        cls.empty = Company.objects.create(
            id='home-v219-empty', source_url='https://example.test/company/hp-empty',
            source_name='archive', display_name='مؤسسه بدون تجربه',
            source_work_count=0, source_interview_count=0,
        )
        cls.staff = get_user_model().objects.create_superuser(
            username='homepage-v219-staff', email='homepage-v219@example.test',
            password='unused-for-production',
        )
        cls.regular = get_user_model().objects.create_user(
            username='homepage-v219-regular', password='unused-for-production',
        )
        exp = PublicExperience.objects.create(
            company=cls.first, source_url='https://example.test/private/hp-v219',
            source_kind='work', title='PRIVATE_HOMEPAGE_SENTINEL',
            body='PRIVATE_HOMEPAGE_BODY_927413 must remain private',
            content_sha256='a' * 64,
        )
        # Source counters are unverified hints; public-listable record counts
        # exclude blocked/rejected/duplicate and non-HTTP source links.
        for idx in range(2):
            PublicExperience.objects.create(
                company=cls.second, source_url=f'https://example.test/interview/{idx}',
                source_kind='interview', title='نمونهٔ مصاحبه',
                body='متن خصوصی مصاحبه', content_sha256=str(idx + 2) * 64,
            )
        for idx, overrides in enumerate((
            {'copyright_review': 'blocked'},
            {'company_attribution_status': 'rejected'},
            {'independence_status': 'duplicate'},
            {'source_url': 'ftp://example.test/hidden'},
        )):
            PublicExperience.objects.create(
                company=cls.first,
                source_url=overrides.pop('source_url', f'https://example.test/hidden/{idx}'),
                source_kind='work', title='BLOCKED_META_SENTINEL',
                body='PRIVATE_BLOCKED_BODY', content_sha256=str(idx + 5) * 64,
                **overrides,
            )
        CriteriaAnalysis.objects.create(
            experience=exp, criteria_version='work6_v2',
            source_content_sha256='a' * 64,
            model_name='never-public-in-homepage', prompt_version='test',
            run_id='homepage-v219-confidential-run',
            raw_payload={'secret': 'PRIVATE_HOMEPAGE_PAYLOAD_927413'},
            review_status='pilot_unverified',
        )

    def setUp(self):
        self.url = reverse('homepage-preview-v219')

    def _authorized(self):
        self.client.force_login(self.staff)
        return patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PREVIEW_ENABLED': '1'})

    def test_url_is_private_and_off_by_default(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PREVIEW_ENABLED': '0'}):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_and_nonstaff_are_denied(self):
        with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PREVIEW_ENABLED': '1'}):
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.client.force_login(self.regular)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_source_mock_scores_private_text_and_raw_payload_never_render(self):
        with self._authorized():
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'آزمون الف')
        self.assertContains(response, 'امتیاز موجود نیست')
        for marker in ('PRIVATE_HOMEPAGE_SENTINEL', 'PRIVATE_HOMEPAGE_BODY_927413',
                       'PRIVATE_HOMEPAGE_PAYLOAD_927413', 'demo_nova', 'previewScores',
                       '۷.۸', '۷.۲', '۶.۹', '۴۰ تحلیل'):
            self.assertNotContains(response, marker)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('noindex', response['X-Robots-Tag'])
        self.assertIn('frame-ancestors', response['Content-Security-Policy'])
        self.assertNotIn('unsafe-eval', response['Content-Security-Policy'])

    def test_work_and_interview_sort_separately_without_scores(self):
        with self._authorized():
            work = self.client.get(self.url)
            interview = self.client.get(self.url, {'mode': 'interview'})
        self.assertLess(work.content.index('آزمون الف'.encode()), work.content.index('آزمون ب'.encode()))
        self.assertLess(interview.content.index('آزمون ب'.encode()), interview.content.index('آزمون الف'.encode()))
        self.assertContains(work, 'حقوق، مزایا و عدالت پرداخت')
        self.assertContains(interview, 'احترام و رفتار حرفه‌ای')
        self.assertNotContains(interview, 'حقوق، مزایا و عدالت پرداخت')
        self.assertNotContains(interview, 'source_work_count')

    def test_search_and_boolean_filters_apply_server_side(self):
        with self._authorized():
            response = self.client.get(self.url, {'q': 'آزمون الف'})
            verified = self.client.get(self.url, {'verified': '1'})
            has_records = self.client.get(self.url, {'has_records': '1'})
            interview = self.client.get(self.url, {'mode': 'interview', 'has_records': '1'})
        self.assertContains(response, 'آزمون الف')
        self.assertNotContains(response, 'آزمون ب')
        self.assertContains(verified, 'آزمون ب')
        self.assertNotContains(verified, 'آزمون الف')
        self.assertNotContains(has_records, 'مؤسسه بدون تجربه')
        self.assertNotContains(interview, 'مؤسسه بدون تجربه')

    def test_map_scripts_are_not_eagerly_loaded_before_verified_pins(self):
        with self._authorized():
            html = self.client.get(self.url).content.decode()
        self.assertNotIn('src="https://unpkg.com/maplibre-gl', html)
        self.assertNotIn('href="https://unpkg.com/maplibre-gl', html)
        self.assertIn('companies/js/homepage_preview_v219.js', html)

    def test_only_verified_api_is_present_no_hardcoded_pin(self):
        with self._authorized():
            html = self.client.get(self.url).content.decode()
        self.assertIn(reverse('verified-company-locations'), html)
        self.assertIn('companies/js/homepage_preview_v219.js', html)
        self.assertNotIn('data-id="digikala"', html)
        self.assertNotIn('موقعیت‌ها نمایشی هستند', html)
        self.assertNotIn('data:image/svg+xml;base64', html)
        self.assertIn('data-company-id=', html)

    def test_counts_match_public_company_details_not_unreviewed_source_counters(self):
        with self._authorized():
            work = self.client.get(self.url)
            interview = self.client.get(self.url, {'mode': 'interview'})
            only_work = self.client.get(self.url, {'has_records': '1'})
            only_interview = self.client.get(self.url, {'mode': 'interview', 'has_records': '1'})
        self.assertEqual(work.status_code, 200)
        self.assertEqual(interview.status_code, 200)
        count_by_id = {c.pk: c.experience_count for c in work.context['page'].object_list}
        self.assertEqual(count_by_id[self.first.pk], 1)
        self.assertEqual(count_by_id[self.second.pk], 0)
        self.assertEqual({c.pk: c.experience_count for c in interview.context['page'].object_list}[self.second.pk], 2)
        self.assertEqual({c.pk for c in only_work.context['page'].object_list}, {self.first.pk})
        self.assertEqual({c.pk for c in only_interview.context['page'].object_list}, {self.second.pk})
        self.assertNotContains(work, 'BLOCKED_META_SENTINEL')
        self.assertNotContains(work, 'PRIVATE_BLOCKED_BODY')
        self.assertNotContains(work, '۱۴ تجربه')
        self.assertNotContains(interview, '۱۵ تجربه')

    def test_get_does_not_write_or_update_analyses(self):
        before = list(CriteriaAnalysis.objects.values_list('run_id', 'raw_payload'))
        with self._authorized():
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(before, list(CriteriaAnalysis.objects.values_list('run_id', 'raw_payload')))

    def test_invalid_options_fail_to_safe_defaults(self):
        with self._authorized():
            response = self.client.get(self.url, {'mode': 'unknown', 'sort': 'bad', 'page': '-4'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['mode'], 'work')
        self.assertEqual(response.context['sort'], 'most')
        self.assertEqual(response.context['page'].number, 1)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['stage.example.test', 'testserver'])
    def test_production_like_preview_requires_https_and_exact_host(self):
        with self._authorized(), patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_STAGING_ENABLED': '1',
            'JOBIEW_HOMEPAGE_STAGING_HOST': 'stage.example.test',
            'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'www.example.test',
            'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
        }):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='testserver', secure=True).status_code, 404)
            self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test').status_code, 404)
            self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 200)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['stage.example.test'])
    def test_staging_requires_explicit_distinct_public_hostname(self):
        with self._authorized(), patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_STAGING_ENABLED': '1',
            'JOBIEW_HOMEPAGE_STAGING_HOST': 'stage.example.test',
            'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'stage.example.test',
            'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
        }):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 404)
            with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_HOST': ''}):
                self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 404)
            with patch.dict('os.environ', {'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'www.example.test'}):
                self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 200)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['stage.example.test', 'www.example.test'])
    def test_staging_does_not_share_allowed_hosts_with_production(self):
        with self._authorized(), patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_STAGING_ENABLED': '1',
            'JOBIEW_HOMEPAGE_STAGING_HOST': 'stage.example.test',
            'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'www.example.test',
            'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
        }):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 404)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['.example.test'])
    def test_staging_rejects_django_suffix_wildcard_host_in_allowlist(self):
        """A dotted Django host pattern also accepts the production hostname."""
        with self._authorized(), patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_STAGING_ENABLED': '1',
            'JOBIEW_HOMEPAGE_STAGING_HOST': 'stage.example.test',
            'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'www.example.test',
            'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
        }):
            self.assertEqual(
                self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 404
            )

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['*'])
    def test_staging_rejects_global_wildcard_hosts(self):
        with self._authorized(), patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_STAGING_ENABLED': '1',
            'JOBIEW_HOMEPAGE_STAGING_HOST': 'stage.example.test',
            'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'www.example.test',
            'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
        }):
            self.assertEqual(
                self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 404
            )

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['stage.example.test'])
    def test_prod_publication_gate_cannot_open_preview(self):
        with self._authorized(), patch.dict('os.environ', {
            'JOBIEW_HOMEPAGE_STAGING_ENABLED': '1',
            'JOBIEW_HOMEPAGE_STAGING_HOST': 'stage.example.test',
            'JOBIEW_HOMEPAGE_PUBLIC_HOST': 'www.example.test',
            'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1',
        }):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='stage.example.test', secure=True).status_code, 404)