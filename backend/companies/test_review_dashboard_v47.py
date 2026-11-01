"""End-to-end editorial dashboard tests. Do not use the real dev DB or internet."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.html import escape

from companies.models import Company, CompanyVerificationEvent
from locations.models import CompanyLocation, CompanyLocationReviewEvent


class CompanyReviewDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='c728abe6cfd909de6bc6c', source_url='https://example.org/company/test',
            source_name='توسن', display_name='توسن - تست داشبورد',
        )
        cls.other = Company.objects.create(
            id='other-company-0000000000', source_url='https://example.org/company/other',
            source_name='Other', display_name='Another Company',
        )
        cls.admin = get_user_model().objects.create_superuser(
            username='wi-review-admin', email='wi@example.org', password='test-only-secret',
        )

    def setUp(self):
        self.url = reverse('admin:companies_company_review', args=[self.company.pk])
        self.client.force_login(self.admin)

    def post_company(self, field, decision='verified', **kw):
        return self.client.post(self.url, {
            'review_kind': 'company', 'verification_field': field,
            f'verification-{field}-decision': decision,
            f'verification-{field}-evidence_url': kw.get('evidence', 'https://official.example.org/contact'),
            f'verification-{field}-rationale': kw.get('reason', 'منبع مستقل مرتبط بررسی شد و نتیجه ثبت شد.'),
        })

    def post_location(self, **kw):
        return self.client.post(self.url, {
            'review_kind': 'location',
            'decision': kw.get('decision','verified'),
            'address': kw.get('address','تهران، خیابان نمونه، پلاک ۱۲'),
            'latitude': kw.get('latitude','35.720000'),
            'longitude': kw.get('longitude','51.440000'),
            'evidence_url': kw.get('evidence','https://official.example.org/contact'),
            'rationale': kw.get('reason','آدرس رسمی دفتر با نقطه نقشه تطبیق داده شد.'),
            'company': self.other.pk, 'reviewer': '9999',
        })

    def test_dashboard_renders_four_checks_and_existing_map(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for value in ['هویت شرکت', 'حوزه فناوری', 'ارتباط با تهران', 'مکان دفتر شرکت',
                      'wi-location-picker', 'id_latitude', 'id_longitude', 'id_address',
                      'review_evidence_helper_v46.js', 'location_picker_v39.js']:
            self.assertContains(response, value)
        self.assertContains(response, 'تمام پیش‌شرط‌های نمایش در نقشه عمومی را ندارد')
        self.assertContains(self.client.get(reverse('admin:companies_company_changelist')), 'داشبورد بررسی')
        self.assertContains(self.client.get(reverse('admin:companies_company_change',args=[self.company.pk])), 'ورود به داشبورد بررسی همین شرکت')
        self.assertEqual(CompanyVerificationEvent.objects.count(), 0)

    def test_three_independent_checks_update_through_events(self):
        for field, attr in [('identity','identity_status'), ('tech','tech_status'), ('tehran','tehran_status')]:
            result = self.post_company(field)
            self.assertEqual(result.status_code, 302)
            self.company.refresh_from_db()
            self.assertEqual(getattr(self.company,attr), 'verified')
            self.assertEqual(CompanyVerificationEvent.objects.filter(company=self.company,field=field).count(),1)
        self.assertEqual(CompanyVerificationEvent.objects.count(),3)
        self.assertFalse(CompanyLocation.objects.filter(company=self.company).exists())

    def test_location_review_preserves_audit_and_does_not_trust_posted_company(self):
        response = self.post_location()
        self.assertEqual(response.status_code,302)
        self.assertEqual(CompanyLocationReviewEvent.objects.filter(company=self.company).count(),1)
        self.assertEqual(CompanyLocationReviewEvent.objects.filter(company=self.other).count(),0)
        event = CompanyLocationReviewEvent.objects.get(company=self.company)
        self.assertEqual(event.reviewer_id, self.admin.pk)
        loc = CompanyLocation.objects.get(company=self.company)
        self.assertEqual(loc.verification_status, 'verified')
        self.assertEqual(str(loc.latitude), '35.720000')
        response = self.client.get(self.url)
        self.assertContains(response, '35.720000')
        self.assertContains(response, 'تهران، خیابان نمونه، پلاک ۱۲')
        self.assertContains(response, 'آخرین بررسی مکان')

    def test_reject_missing_evidence_and_rationale_without_writes(self):
        response = self.post_company('identity',evidence='')
        self.assertEqual(response.status_code,200)
        self.assertEqual(CompanyVerificationEvent.objects.count(),0)
        response = self.post_location(evidence='')
        self.assertEqual(response.status_code,200)
        self.assertEqual(CompanyLocationReviewEvent.objects.count(),0)
        self.assertFalse(CompanyLocation.objects.exists())
        response = self.post_location(reason='short')
        self.assertEqual(response.status_code,200)
        self.assertFalse(CompanyLocation.objects.exists())

    def test_verify_location_alone_does_not_publish_to_public_geojson(self):
        self.post_location()
        r = self.client.get(reverse('verified-company-locations')).json()
        self.assertEqual(r['features'],[])
        for field in ('identity','tech','tehran'):
            self.post_company(field)
        response = self.client.get(self.url)
        self.assertContains(response, 'تمام پیش‌شرط‌های فعلی نمایش مکان در نقشه عمومی برقرارند')
        features = self.client.get(reverse('verified-company-locations')).json()['features']
        self.assertEqual(len(features),1)
        self.assertEqual(features[0]['properties']['company_id'],self.company.pk)
        self.post_company('tech',decision='rejected', reason='اطلاعات فعلی با این طبقه‌بندی تطبیق ندارد.')
        self.assertEqual(self.client.get(reverse('verified-company-locations')).json()['features'],[])

    def test_rejected_location_revokes_public_and_retains_previous_coordinates(self):
        self.post_location()
        for f in ('identity','tech','tehran'): self.post_company(f)
        self.assertEqual(len(self.client.get(reverse('verified-company-locations')).json()['features']),1)
        r = self.post_location(decision='rejected',reason='مکان قبلی متعلق به این شرکت نیست و بررسی شد.', evidence='')
        self.assertEqual(r.status_code,302)
        location=CompanyLocation.objects.get(company=self.company)
        self.assertEqual(location.verification_status,'rejected')
        self.assertIsNone(location.verified_at)
        self.assertEqual(self.client.get(reverse('verified-company-locations')).json()['features'],[])
        self.assertEqual(CompanyLocationReviewEvent.objects.filter(company=self.company).count(),2)

    def test_malicious_field_and_missing_permission_rejected(self):
        response=self.post_company('unexpected')
        self.assertEqual(response.status_code,404)
        user=get_user_model().objects.create_user(username='wi-minimal',password='test',is_staff=True)
        perms=Permission.objects.filter(content_type__app_label='companies',codename='view_company')
        user.user_permissions.add(*perms)
        client=Client();client.force_login(user)
        self.assertEqual(client.get(self.url).status_code,200)
        self.assertNotContains(client.get(self.url),'<form method="post"',html=False)
        self.assertEqual(client.post(self.url,{'review_kind':'location','decision':'verified'}).status_code,403)
        self.assertEqual(client.post(self.url,{'review_kind':'company','verification_field':'identity'}).status_code,403)
        self.assertEqual(CompanyVerificationEvent.objects.count(),0)

    def test_requires_admin_company_view_permission(self):
        user=get_user_model().objects.create_user(username='wi-no-view',password='test',is_staff=True)
        client=Client();client.force_login(user)
        self.assertEqual(client.get(self.url).status_code,403)

    def test_rejects_missing_or_unknown_target(self):
        self.assertEqual(self.client.get(reverse('admin:companies_company_review', args=['missing-company'])).status_code,404)
        self.assertEqual(self.client.post(self.url,{'review_kind':'other'}).status_code,404)

    def test_html_output_escapes_untrusted_company_name(self):
        self.company.display_name='<script>alert(1)</script>'
        self.company.save(update_fields=['display_name'])
        response=self.client.get(self.url)
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertContains(response,escape(self.company.display_name))

    def test_crsf_required_for_post(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response=client.post(self.url,{'review_kind':'company','verification_field':'identity'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(CompanyVerificationEvent.objects.count(),0)
