"""V38: admin map supports human coordinate picking without weakening validation."""
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from locations.models import CompanyLocation, CompanyLocationReviewEvent


class AdminMapPickerV38Tests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            'map-editor-v38', 'map-editor@example.invalid', 'test-only-password'
        )
        self.client.force_login(self.user)
        self.company = Company.objects.create(
            id='map_v38', source_url='https://example.invalid/companies/map_v38',
            source_name='شرکت آزمایشی', display_name='شرکت آزمایشی',
        )
        self.add_url = reverse('admin:locations_companylocationreviewevent_add')

    def form_data(self, **overrides):
        body = {
            'company': self.company.pk,
            'decision': 'verified',
            'address': 'تهران، خیابان مثال، کوچه آزمایش، پلاک ۱۴',
            'latitude': '35.730123',
            'longitude': '51.424567',
            'evidence_url': 'https://example.invalid/evidence/company-location',
            'rationale': 'موقعیت با منبع معتبر بررسی و روی نقشه انتخاب شده است',
            '_save': 'Save',
        }
        body.update(overrides)
        return body

    def test_add_page_contains_interactive_map_and_original_fields(self):
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)
        for expected in (
            'wi-location-picker', 'wi-location-map', 'wi-location-search-button',
            'id_latitude', 'id_longitude', 'id_address', 'id_evidence_url',
            'location_picker_v39.js', 'maplibre-gl@5.6.0', 'نقشه',
        ):
            self.assertContains(response, expected)

    def test_map_assets_are_packaged_as_staticfiles(self):
        for name in ('locations/js/location_picker_v39.js',
                     'locations/css/location_picker_v38.css'):
            found = finders.find(name)
            self.assertTrue(found, name)
            self.assertTrue(Path(found).is_file())

    def test_picked_coordinates_are_saved_as_review_event(self):
        response = self.client.post(self.add_url, self.form_data())
        self.assertEqual(response.status_code, 302)
        event = CompanyLocationReviewEvent.objects.get()
        self.assertEqual(event.latitude, Decimal('35.730123'))
        self.assertEqual(event.longitude, Decimal('51.424567'))
        self.assertEqual(event.reviewer_id, self.user.pk)
        location = CompanyLocation.objects.get(company=self.company)
        self.assertEqual(location.latitude, event.latitude)
        self.assertEqual(location.longitude, event.longitude)

    def test_map_pick_without_evidence_cannot_approve(self):
        response = self.client.post(self.add_url, self.form_data(evidence_url=''))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 0)
        self.assertEqual(CompanyLocation.objects.count(), 0)

    def test_map_pick_without_address_cannot_approve(self):
        response = self.client.post(self.add_url, self.form_data(address=''))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 0)

    def test_validates_coordinate_ranges_even_with_map_ui(self):
        response = self.client.post(self.add_url, self.form_data(latitude='100'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 0)

    def test_rejection_does_not_require_map_or_coordinates(self):
        data = self.form_data(decision='rejected', address='', latitude='',
                              longitude='', evidence_url='',
                              rationale='این شرکت در این نشانی فعالیت ندارد و موقعیت رد شد')
        response = self.client.post(self.add_url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CompanyLocationReviewEvent.objects.get().decision, 'rejected')

    def test_map_selection_alone_does_not_publish_public_pin(self):
        self.client.post(self.add_url, self.form_data())
        self.assertEqual(self.client.get(reverse('verified-company-locations')).json()['features'], [])

    def test_admin_history_is_readonly_and_append_only(self):
        self.client.post(self.add_url, self.form_data())
        event = CompanyLocationReviewEvent.objects.get()
        change_url = reverse('admin:locations_companylocationreviewevent_change', args=[event.pk])
        response = self.client.get(change_url)
        self.assertIn(response.status_code, (200, 403))
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 1)
