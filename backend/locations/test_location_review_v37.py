import csv
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, RequestFactory
from django.urls import reverse

from companies.models import Company, CompanyVerificationEvent
from locations.admin import CompanyLocationAdmin
from locations.models import CompanyLocation, CompanyLocationReviewEvent


class LocationReviewV37Tests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('geoeditor', 'geoeditor@example.invalid', 'test-only-pwd')
        self.co = Company.objects.create(id='c37', source_url='https://sample.example/co',
                                         source_name='شرکت آزمایشی', display_name='شرکت آزمایشی',
                                         source_work_count=14, source_interview_count=1)

    def event(self, **overrides):
        data = dict(company=self.co, reviewer=self.user, decision='verified',
                    address='تهران، خیابان نمونه، پلاک ۱۲', latitude=Decimal('35.710000'),
                    longitude=Decimal('51.410000'), evidence_url='https://sample.example/location',
                    rationale='نشانی و مختصات با منبع مستند بررسی و ثبت شد')
        data.update(overrides)
        return CompanyLocationReviewEvent.objects.create(**data)

    def company_approve(self, field):
        CompanyVerificationEvent.objects.create(company=self.co, reviewer=self.user,
            field=field, decision='verified', evidence_url='https://sample.example/company',
            rationale='هویت و نوع فعالیت و حوزه مکانی با سند رسمی تأیید شد')

    def features(self):
        return self.client.get(reverse('verified-company-locations')).json()['features']

    def test_unverified_is_empty_and_map_page_exists(self):
        self.assertEqual(self.features(), [])
        response = self.client.get(reverse('company-map'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فقط مکان‌هایی نمایش داده می‌شوند')

    def test_location_event_alone_not_published(self):
        self.event()
        self.assertEqual(self.features(), [])
        for field in ('identity', 'tech', 'tehran'):
            self.company_approve(field)
        data = self.features()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['geometry']['coordinates'], [51.41, 35.71])
        self.assertEqual(set(data[0]['properties']), {'company_id', 'name'})

    def test_requires_complete_evidence_for_approval(self):
        for field, value in [('evidence_url', ''), ('address', ''), ('longitude', None),
                             ('latitude', Decimal('95.000000')), ('rationale', 'مختصر')]:
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.event(**{field: value})
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 0)
        self.assertEqual(CompanyLocation.objects.count(), 0)

    def test_revocation_hides_pin_preserves_history(self):
        for field in ('identity', 'tech', 'tehran'):
            self.company_approve(field)
        first = self.event()
        self.assertEqual(len(self.features()), 1)
        CompanyLocationReviewEvent.objects.create(company=self.co, reviewer=self.user,
            decision='rejected', rationale='نشانی قبلی متعلق به شرکت دیگری بوده و رد می‌شود')
        self.assertEqual(self.features(), [])
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 2)
        with self.assertRaises(ValueError):
            first.save()
        with self.assertRaises(ValueError):
            first.delete()
        self.assertIsNone(CompanyLocation.objects.get(company=self.co).verified_at)
        self.assertEqual(CompanyLocation.objects.get(company=self.co).address, 'تهران، خیابان نمونه، پلاک ۱۲')

    def test_company_revocation_hides_pin(self):
        for field in ('identity', 'tech', 'tehran'):
            self.company_approve(field)
        self.event()
        self.assertEqual(len(self.features()), 1)
        CompanyVerificationEvent.objects.create(company=self.co, reviewer=self.user,
            field='tehran', decision='rejected', rationale='مدرک اتصال مکانی قابل استناد نبود')
        self.assertEqual(self.features(), [])

    def test_direct_location_update_without_matching_review_hidden(self):
        for field in ('identity', 'tech', 'tehran'):
            self.company_approve(field)
        self.event()
        CompanyLocation.objects.filter(company=self.co).update(latitude=Decimal('36.000000'))
        self.assertEqual(self.features(), [])

    def test_admin_can_add_review_not_edit_location(self):
        admin = CompanyLocationAdmin(CompanyLocation, AdminSite())
        self.assertFalse(admin.has_add_permission(RequestFactory().get('/admin/')))
        self.client.force_login(self.user)
        response = self.client.get(reverse('admin:locations_companylocationreviewevent_add'))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('admin:locations_companylocationreviewevent_add'), {
            'company': self.co.pk, 'decision': 'verified',
            'address': 'تهران، خیابان نمونه، پلاک ۱۲',
            'latitude': '35.710000', 'longitude': '51.410000',
            'evidence_url': 'https://sample.example/location',
            'rationale': 'آدرس و مختصات براساس منبع موجود بازبینی شد', '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 1)
        self.assertEqual(CompanyLocationReviewEvent.objects.get().reviewer_id, self.user.pk)

    def test_export_queue_does_not_modify_db_and_writes_utf8_excel(self):
        with TemporaryDirectory() as folder:
            out = Path(folder) / 'queue.csv'
            captured = StringIO()
            call_command('export_company_review_queue', out=str(out), limit=5, stdout=captured)
            rows = list(csv.DictReader(out.open(encoding='utf-8-sig', newline='')))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['company_id'], self.co.pk)
            self.assertEqual(rows[0]['company_name'], 'شرکت آزمایشی')
            self.assertEqual(rows[0]['location_status'], 'unverified')
            self.assertIn('"database_writes": 0', captured.getvalue())
            self.assertEqual(CompanyLocationReviewEvent.objects.count(), 0)

    def test_existing_location_stays_hidden_without_decision(self):
        for field in ('identity', 'tech', 'tehran'):
            self.company_approve(field)
        from django.utils import timezone
        CompanyLocation.objects.create(company=self.co, verification_status='verified',
            latitude=Decimal('35.700000'), longitude=Decimal('51.400000'),
            evidence_url='https://sample.example/manual', verified_at=timezone.now())
        self.assertEqual(self.features(), [])
