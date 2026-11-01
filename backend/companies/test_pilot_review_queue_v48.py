"""Regression tests for PRD 0.1 pilot triage. No real DB, internet or AI calls."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company, CompanyVerificationEvent
from locations.models import CompanyLocation, CompanyLocationReviewEvent


class PilotReviewQueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username='v48-admin', email='v48@example.invalid', password='testing-only',
        )
        cls.low = cls.company('low', 'شرکت آلفا', 2, 1)
        cls.high = cls.company('high', 'شرکت بتا', 10, 3)
        cls.empty = cls.company('empty', 'شرکت گاما', 0, 0)
        cls.reject = cls.company('rejected', 'شرکت رد شده', 100, 4)
        cls.reject.identity_status = 'rejected'
        cls.reject.save(update_fields=['identity_status'])
        cls.ready = cls.company('ready', 'شرکت تأییدشده', 6, 0)
        cls.partial = cls.company('partial', 'شرکت درحال بررسی', 3, 2)
        CompanyVerificationEvent.objects.create(
            company=cls.partial, field='identity', decision='verified',
            reviewer=cls.admin, evidence_url='https://example.org/official',
            rationale='هویت شرکت از طریق مدرک رسمی بررسی شد.',
        )
        for field in ('identity', 'tech', 'tehran'):
            CompanyVerificationEvent.objects.create(
                company=cls.ready, field=field, decision='verified',
                reviewer=cls.admin, evidence_url='https://example.org/contact',
                rationale='شواهد مستقل شرکت برای بررسی مناسب بود.',
            )
        CompanyLocationReviewEvent.objects.create(
            company=cls.ready, decision='verified', reviewer=cls.admin,
            address='تهران، خیابان آزمایشی، پلاک ۱', latitude='35.719000',
            longitude='51.430000', evidence_url='https://example.org/contact',
            rationale='نشانی دفتر با صفحه رسمی شرکت تطبیق داده شد.',
        )

    @staticmethod
    def company(pk, name, work, interview):
        return Company.objects.create(
            id='pilot-' + pk, source_url=f'https://example.org/{pk}',
            source_name=name, display_name=name, source_work_count=work,
            source_interview_count=interview,
        )

    def setUp(self):
        self.url = reverse('admin:companies_company_pilot_review_queue')
        self.client.force_login(self.admin)

    def test_default_queue_excludes_rejected_and_ready_without_writes(self):
        before_companies = list(Company.objects.values_list('pk', 'identity_status', 'tech_status', 'tehran_status'))
        before_events = CompanyVerificationEvent.objects.count()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        ids = [r['company'].pk for r in response.context['rows']]
        self.assertEqual(ids, [self.high.pk, self.partial.pk, self.low.pk, self.empty.pk])
        self.assertEqual(response.context['total_companies'], 6)
        self.assertEqual(response.context['matched_count'], 4)
        self.assertEqual(before_companies, list(Company.objects.values_list('pk', 'identity_status', 'tech_status', 'tehran_status')))
        self.assertEqual(CompanyVerificationEvent.objects.count(), before_events)
        self.assertContains(response, 'معیار نهایی پذیرش پایلوت هنوز تصویب نشده')
        self.assertContains(response, 'صفحه قبل', count=0)

    def test_status_filters_are_descriptive_not_auto_decisions(self):
        expected = {
            'unreviewed': {self.low.pk, self.high.pk, self.empty.pk},
            'partial': {self.partial.pk},
            'map_ready': {self.ready.pk},
            'rejected': {self.reject.pk},
            'all': {c.pk for c in [self.low,self.high,self.empty,self.reject,self.ready,self.partial]},
        }
        for stage, expected_ids in expected.items():
            with self.subTest(stage=stage):
                response = self.client.get(self.url, {'stage': stage})
                self.assertEqual({r['company'].pk for r in response.context['rows']}, expected_ids)
        self.assertEqual(Company.objects.filter(vote_enabled=True).count(), 0)

    def test_coverage_sort_search_and_invalid_query(self):
        response = self.client.get(self.url, {'coverage': 'five', 'stage': 'all'})
        self.assertEqual({r['company'].pk for r in response.context['rows']},
                         {self.high.pk, self.ready.pk, self.reject.pk})
        response = self.client.get(self.url, {'q': 'بتا', 'stage': 'all'})
        self.assertEqual([r['company'].pk for r in response.context['rows']], [self.high.pk])
        response = self.client.get(self.url, {'stage': 'all', 'sort': 'name'})
        self.assertEqual([r['company'].display_name for r in response.context['rows']],
                         sorted(c.display_name for c in [self.low,self.high,self.empty,self.reject,self.ready,self.partial]))
        response = self.client.get(self.url, {'stage': 'invalid', 'sort': 'wrong', 'coverage': 'xyz', 'page': 'nonsense'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.context['stage'], response.context['sort'],response.context['coverage']), ('pending','work','any'))

    def test_map_ready_filter_matches_public_geojson(self):
        response = self.client.get(self.url, {'stage': 'map_ready'})
        eligible = {r['company'].pk for r in response.context['rows']}
        actual = {f['properties']['company_id'] for f in self.client.get(reverse('verified-company-locations')).json()['features']}
        self.assertEqual(eligible, actual)
        self.assertEqual(eligible, {self.ready.pk})
        # A direct status edit cannot bypass append-only review evidence.
        self.low.identity_status = self.low.tech_status = self.low.tehran_status = 'verified'
        self.low.save(update_fields=['identity_status','tech_status','tehran_status'])
        CompanyLocation.objects.create(
            company=self.low, latitude='35.700000', longitude='51.400000',
            verification_status='verified', verified_at=timezone.now(),
            evidence_url='https://example.org/suspicious',
        )
        response = self.client.get(self.url, {'stage': 'map_ready'})
        self.assertEqual({r['company'].pk for r in response.context['rows']}, {self.ready.pk})

    def test_rejected_review_blocks_default_even_if_source_count_large(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, self.reject.display_name)
        self.assertContains(self.client.get(self.url, {'stage':'rejected'}), self.reject.display_name)

    def test_only_staff_with_company_view_access(self):
        client = Client()
        self.assertEqual(client.get(self.url).status_code, 302)
        user = get_user_model().objects.create_user(username='wi-48-staff',password='test',is_staff=True)
        client.force_login(user)
        self.assertEqual(client.get(self.url).status_code, 403)
        user.user_permissions.add(Permission.objects.get(content_type__app_label='companies', codename='view_company'))
        self.assertEqual(client.get(self.url).status_code, 200)
        self.assertEqual(client.post(self.url, {}).status_code, 405)
        self.assertEqual(CompanyVerificationEvent.objects.count(),4)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(),1)

    def test_company_admin_list_links_to_queue(self):
        response = self.client.get(reverse('admin:companies_company_changelist'))
        self.assertContains(response, reverse('admin:companies_company_pilot_review_queue'))
        self.assertContains(response, 'صف بررسی نامزدهای پایلوت')

    def test_untrusted_name_is_escaped(self):
        self.low.display_name = '<img src=x onerror=alert(1)>'
        self.low.save(update_fields=['display_name'])
        response = self.client.get(self.url)
        self.assertNotContains(response, '<img src=x onerror=alert(1)>', html=False)
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;', html=False)

    def test_paginated_results_preserve_validated_filters(self):
        Company.objects.bulk_create([
            Company(id=f'bulk-{i}',source_url=f'https://example.org/bulk-{i}',
                    source_name='Test',display_name=f'نامزد {i}',source_work_count=3)
            for i in range(35)
        ])
        response = self.client.get(self.url, {'stage':'all','coverage':'one', 'sort':'name', 'page': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['rows']), 15)
        self.assertContains(response, 'stage=all&amp;coverage=one&amp;sort=name&amp;page=1')
