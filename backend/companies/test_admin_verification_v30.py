from io import StringIO
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, RequestFactory
from companies.admin import CompanyAdmin
from companies.models import Company, CompanyVerificationEvent


class CompanyVerificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('reviewer', 'reviewer@example.invalid', 'SafePwd123!')
        self.company = Company.objects.create(
            id='c30', source_url='https://example.org/co', source_name='شرکت آزمایشی', display_name='شرکت آزمایشی'
        )

    def test_positive_requires_source_and_note(self):
        event = CompanyVerificationEvent(company=self.company, reviewer=self.user,
            field='identity', decision='verified', rationale='شاهد معتبر برای هویت شرکت')
        with self.assertRaises(ValidationError):
            event.save()
        self.company.refresh_from_db()
        self.assertEqual(self.company.identity_status, 'unverified')

    def test_verified_and_revoked_both_auditable(self):
        event = CompanyVerificationEvent.objects.create(company=self.company, reviewer=self.user,
            field='identity', decision='verified', evidence_url='https://example.org/evidence',
            rationale='هویت شرکت با منبع رسمی بررسی و تأیید شد')
        self.company.refresh_from_db()
        self.assertEqual(self.company.identity_status, 'verified')
        with self.assertRaises(ValueError):
            event.decision='rejected'; event.save()
        CompanyVerificationEvent.objects.create(company=self.company, reviewer=self.user,
            field='identity', decision='rejected', rationale='منبع قبلی برای انتساب هویت معتبر نیست')
        self.company.refresh_from_db()
        self.assertEqual(self.company.identity_status, 'rejected')
        self.assertEqual(CompanyVerificationEvent.objects.count(), 2)
        self.assertFalse(self.company.vote_enabled)

    def test_company_admin_protects_decision_fields(self):
        ma = CompanyAdmin(Company, AdminSite())
        self.assertIn('identity_status', ma.readonly_fields)
        self.assertIn('vote_enabled', ma.readonly_fields)
        self.assertFalse(ma.has_add_permission(RequestFactory().get('/admin/')))

    def test_readiness_private_and_offline(self):
        out = StringIO()
        call_command('product_readiness', stdout=out)
        self.assertIn('"companies": 1', out.getvalue())
        self.assertIn('"claude_network_requests": 0', out.getvalue())
        self.assertNotIn('SafePwd123', out.getvalue())

    def test_admin_can_create_evidence_backed_event(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        page = self.client.get(reverse('admin:companies_companyverificationevent_add'))
        self.assertEqual(page.status_code, 200)
        response = self.client.post(reverse('admin:companies_companyverificationevent_add'), {
            'company': self.company.pk,
            'field': 'identity', 'decision': 'verified',
            'evidence_url': 'https://example.org/reliable-evidence',
            'rationale': 'منبع مستقل برای شناسایی شرکت بررسی شده است',
            '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.identity_status, 'verified')
        event = CompanyVerificationEvent.objects.get()
        self.assertEqual(event.reviewer, self.user)
