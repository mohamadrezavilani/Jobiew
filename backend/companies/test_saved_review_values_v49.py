"""Regression for persisted review values on the company dashboard.

Tests use Django's isolated test DB; never the user's production/dev DB.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import Company, CompanyVerificationEvent
from locations.models import CompanyLocation, CompanyLocationReviewEvent


class SavedReviewValuesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='saved-company-test-001',
            source_url='https://example.org/source/test',
            source_name='آزمایشی', display_name='شرکت آزمایشی',
        )
        cls.other = Company.objects.create(
            id='saved-company-other-002',
            source_url='https://example.org/source/other',
            source_name='دیگری', display_name='شرکت دیگر',
        )
        cls.editor = get_user_model().objects.create_superuser(
            username='v49-editor', email='v49@example.org', password='unused-test-only',
        )

    def setUp(self):
        self.client.force_login(self.editor)
        self.url = reverse('admin:companies_company_review', args=[self.company.pk])

    def event(self, field, decision='verified', evidence='https://official.example.org/contact', rationale='این بررسی با مدارک موجود ویرایش و ثبت شد.'):
        return CompanyVerificationEvent.objects.create(
            company=self.company, field=field, decision=decision,
            evidence_url=evidence, rationale=rationale, reviewer=self.editor,
        )

    def location_event(self, **overrides):
        data = dict(company=self.company, reviewer=self.editor, decision='verified',
                    address='تهران، خیابان ولیعصر، پلاک ۱۸', latitude='35.721234',
                    longitude='51.412345', evidence_url='https://official.example.org/contact',
                    rationale='آدرس دفتر و منبع مستقل با موقعیت روی نقشه تطبیق دارد.')
        data.update(overrides)
        return CompanyLocationReviewEvent.objects.create(**data)

    def test_company_forms_prefill_latest_independently_and_show_saved_evidence(self):
        for field in ('identity', 'tech', 'tehran'):
            self.event(field, rationale=f'دلیل ثبت‌شده برای {field} از منبع معتبر بررسی گردید.')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for item in response.context['panels']:
            saved = item['latest']
            self.assertEqual(item['form']['decision'].value(), saved.decision)
            self.assertEqual(item['form']['evidence_url'].value(), saved.evidence_url)
            self.assertEqual(item['form']['rationale'].value(), saved.rationale)
            self.assertContains(response, saved.rationale)
        self.assertContains(response, 'ثبت تصمیم جدید هویت شرکت')
        self.assertEqual(CompanyVerificationEvent.objects.count(), 3)

    def test_newest_company_event_not_older_event_is_displayed(self):
        self.event('identity', decision='verified', rationale='تأیید مبتنی بر مدارک اولیه معتبر ثبت گردید.')
        latest = self.event('identity', decision='rejected', evidence='',
                            rationale='مدرک قبلی دیگر برای اثبات این هویت کافی نیست.')
        response = self.client.get(self.url)
        panel = next(x for x in response.context['panels'] if x['field'] == 'identity')
        self.assertEqual(panel['form']['decision'].value(), 'rejected')
        self.assertEqual(panel['form']['evidence_url'].value(), '')
        self.assertEqual(panel['form']['rationale'].value(), latest.rationale)
        self.assertEqual(CompanyVerificationEvent.objects.count(), 2)

    def test_location_form_prefills_decision_rationale_address_coordinates_and_evidence(self):
        event = self.location_event()
        response = self.client.get(self.url)
        form = response.context['location_form']
        for name in ('decision','address','latitude','longitude','evidence_url','rationale'):
            expected = getattr(event,name)
            self.assertEqual(str(form[name].value()), str(expected))
        self.assertContains(response, 'اطلاعات آخرین تصمیم ثبت‌شده مکان')
        self.assertContains(response, 'ثبت تصمیم جدید مکان شرکت')
        self.assertContains(response, event.rationale)
        self.assertFalse(response.context['location_is_archived'])
        self.assertEqual(CompanyLocationReviewEvent.objects.count(), 1)

    def test_rejected_location_shows_archival_point_warning_and_last_decision(self):
        self.location_event()
        rejected = self.location_event(decision='rejected', address='', latitude=None,
                                      longitude=None, evidence_url='',
                                      rationale='مکان پیشین مربوط به این شرکت نیست و تأیید لغو شد.')
        response = self.client.get(self.url)
        form = response.context['location_form']
        self.assertEqual(form['decision'].value(), 'rejected')
        self.assertEqual(form['rationale'].value(), rejected.rationale)
        self.assertEqual(form['evidence_url'].value(), '')
        self.assertEqual(str(form['latitude'].value()), '35.721234')
        self.assertTrue(response.context['location_is_archived'])
        self.assertContains(response, 'این مکان اکنون تأییدشده نیست')
        self.assertFalse(response.context['public_map_eligible'])
        self.assertEqual(CompanyLocation.objects.get(company=self.company).verification_status, 'rejected')

    def test_unreviewed_company_and_location_keep_empty_initial_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['location_form']['decision'].value(), '')
        self.assertEqual(response.context['location_form']['evidence_url'].value(), '')
        for item in response.context['panels']:
            self.assertEqual(item['form']['rationale'].value(), '')
            self.assertEqual(item['form']['decision'].value(), '')

    def test_invalid_new_review_keeps_user_input_and_other_saved_panels(self):
        self.event('identity')
        self.event('tech', rationale='دلیل ذخیره‌شده برای فناوری از مدرک بررسی شد.')
        response = self.client.post(self.url, {
            'review_kind': 'company', 'verification_field': 'identity',
            'verification-identity-decision': 'verified',
            'verification-identity-evidence_url': '',
            'verification-identity-rationale': 'متنِ همین تلاش ثبت ناموفق جدید است.',
        })
        self.assertEqual(response.status_code, 200)
        identity = next(x for x in response.context['panels'] if x['field']=='identity')
        tech = next(x for x in response.context['panels'] if x['field']=='tech')
        self.assertEqual(identity['form']['evidence_url'].value(), '')
        self.assertEqual(identity['form']['rationale'].value(), 'متنِ همین تلاش ثبت ناموفق جدید است.')
        self.assertEqual(tech['form']['decision'].value(), 'verified')
        self.assertEqual(CompanyVerificationEvent.objects.count(), 2)

    def test_invalid_location_keeps_posted_values_without_overwriting_saved(self):
        self.location_event()
        response = self.client.post(self.url, {
            'review_kind': 'location', 'decision': 'verified', 'address': 'تهران، محل جدید و نامعتبر',
            'latitude': '35.700000', 'longitude': '51.400000', 'evidence_url': '',
            'rationale': 'این تلاش بدون مدرک است و نباید ذخیره شود.',
        })
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['location_form']['address'].value(), 'تهران، محل جدید و نامعتبر')
        self.assertEqual(CompanyLocationReviewEvent.objects.count(),1)
        self.assertEqual(CompanyLocation.objects.get(company=self.company).address, 'تهران، خیابان ولیعصر، پلاک ۱۸')

    def test_no_cross_company_leak_and_no_writes_on_get(self):
        self.location_event()
        self.event('identity')
        response = self.client.get(reverse('admin:companies_company_review', args=[self.other.pk]))
        self.assertEqual(response.context['location_form']['address'].value(), '')
        self.assertFalse(any(item['latest'] for item in response.context['panels']))
        self.assertEqual(CompanyVerificationEvent.objects.count(),1)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(),1)
