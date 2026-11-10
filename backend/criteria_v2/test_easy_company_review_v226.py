"""Fast company verification with genuine human attestation, clear release blockers.

Synthetic records only. Tests HTTPS CSRF, default evidence proposal, append-only
events, stale-form defense, source-rights independence, and release links.
"""
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company, CompanyVerificationEvent
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import CriteriaAnalysis, CriteriaScoreReviewEvent, CriteriaCompanyReleaseEvent
from criteria_v2.registry import axes_for
from experiences.models import PublicExperience, ExperienceReviewEvent

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1',
    'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '1',
    'JOBIEW_COMPANY_RELEASE_ONLY_ENABLED': '1',
}
TEXT = ('در این شرکت حقوق ماهانه با تأخیر پرداخت می‌شد و قرارداد شفاف نبود. '
        'تجربهٔ من مربوط به تأخیر در پرداخت حقوق است و درباره سایر مسائل شاهدی ندارم.')
QUOTE = 'حقوق ماهانه با تأخیر پرداخت می‌شد'


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['jobiew.ir', 'testserver'],
                   CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class EasyCompanyReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='company-v226-simple', source_url='https://example.invalid/company/source',
            source_name='فهرست منبع ساختگی', display_name='شرکت فرضی بررسی ساده',
            identity_status='unverified', tech_status='unverified')
        cls.admin = get_user_model().objects.create_superuser(
            username='review-v226', email='review-v226@example.invalid',
            password='synthetic-only')
        cls.exp = PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.invalid/experience/one',
            title='روایت ساختگی', body=TEXT, content_sha256='d'*64)
        dims = {}
        for n, axis in enumerate(axes_for('work')):
            if n == 0:
                dims[axis.key] = {
                    'score': 4, 'confidence': 91, 'evidence': QUOTE,
                    'explanation': 'متن تجربه تأخیر در پرداخت دستمزد را گزارش می‌کند'
                }
            else:
                dims[axis.key] = {
                    'score': None, 'confidence': 0, 'evidence': '',
                    'explanation': 'در این روایت برای این معیار شاهد کافی وجود ندارد'
                }
        stage_one({
            'experience_id': cls.exp.pk, 'company_id': cls.exp.company_id,
            'kind': 'work', 'source_content_sha256': cls.exp.content_sha256,
            'story_sha256': story_digest(story_from_experience(cls.exp)),
            'model_name': 'synthetic-v226',
            'review_status': 'unverified_private_proposal',
            'prediction': {
                'detected_kind': 'work', 'kind_confidence': 90, 'dimensions': dims,
            },
        })

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.quick_url = reverse('admin:companies_company_checkpoint_verify',
                                 args=[self.company.pk])
        self.release_url = reverse('admin:companies_company_checkpoint_release',
                                   args=[self.company.pk])
        self.bulk_url = reverse('admin:companies_company_checkpoint_bulk',
                                args=[self.company.pk])

    def get(self, url):
        with patch.dict('os.environ', FLAGS):
            return self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')

    def post(self, url, data, **headers):
        with patch.dict('os.environ', FLAGS):
            return self.client.post(url, data, secure=True, HTTP_HOST='jobiew.ir', **headers)

    def data(self, page, identity=True, tech=True):
        out = {
            'snapshot': page.context['snapshot'],
            'evidence_url': self.company.source_url,
            'confirm_evidence': 'on',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
        }
        if identity:
            out['verify_identity'] = 'on'
        if tech:
            out['verify_tech'] = 'on'
        return out

    def approve_scores(self):
        page = self.get(self.bulk_url)
        self.assertEqual(page.status_code, 200)
        response = self.post(self.bulk_url, {
            'snapshot': page.context['token'],
            'ready_count': str(page.context['ready_count']),
            'selected': [str(item['run'].pk) for item in page.context['rows']
                         if not item['reason']],
            'confirm_reviewed': 'yes',
            'confirm_private': 'yes',
            'note': 'متن و شاهدهای شش معیار را به‌صورت واقعی در تست بررسی کردم.',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
        }, HTTP_REFERER='https://jobiew.ir' + self.bulk_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 1)

    def test_get_suggests_evidence_no_automatic_approval(self):
        page = self.get(self.quick_url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        self.assertEqual(page.context['form'].initial['evidence_url'],
                         self.company.source_url)
        self.assertContains(page, 'name="csrfmiddlewaretoken"')
        self.assertContains(page, self.release_url)
        self.assertFalse(CompanyVerificationEvent.objects.exists())

    def test_short_form_approves_two_checked_company_claims_with_audit(self):
        page = self.get(self.quick_url)
        response = self.post(self.quick_url, self.data(page),
                             HTTP_REFERER='https://jobiew.ir' + self.quick_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.release_url)
        self.company.refresh_from_db()
        self.assertEqual(self.company.identity_status, 'verified')
        self.assertEqual(self.company.tech_status, 'verified')
        self.assertEqual(self.company.tehran_status, 'unverified')
        self.assertEqual(CompanyVerificationEvent.objects.count(), 2)
        self.assertEqual(set(CompanyVerificationEvent.objects.values_list('field', flat=True)),
                         {'identity','tech'})
        for event in CompanyVerificationEvent.objects.all():
            self.assertEqual(event.reviewer_id, self.admin.pk)
            self.assertEqual(event.evidence_url, self.company.source_url)
            self.assertGreater(len(event.rationale), 10)
        self.exp.refresh_from_db()
        self.assertEqual(self.exp.copyright_review, 'pending')
        self.assertEqual(self.exp.company_attribution_status, 'unverified')
        self.assertEqual(self.exp.independence_status, 'unknown')
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'pilot_unverified')

    def test_release_lists_real_independent_blockers_and_links(self):
        self.approve_scores()
        page = self.get(self.release_url)
        self.assertEqual(page.status_code, 200)
        stats = page.context['stats']
        self.assertTrue(stats['company_identity_missing'])
        self.assertTrue(stats['company_tech_missing'])
        self.assertEqual(stats['copyright_missing'], 1)
        self.assertEqual(stats['attribution_missing'], 1)
        self.assertEqual(stats['independence_missing'], 1)
        self.assertEqual(stats['classification_missing'], 1)
        self.assertEqual(stats['human_reviewed'], 1)
        self.assertEqual(page.context['eligible_count'], 0)
        self.assertContains(page, self.quick_url)
        self.assertContains(page, 'مجوز واقعی استفاده و انتشار منبع')
        self.assertContains(page, 'ثبت رویداد بررسی منبع')
        self.assertContains(page, 'disabled')
        quick = self.get(self.quick_url)
        response = self.post(self.quick_url, self.data(quick),
                             HTTP_REFERER='https://jobiew.ir' + self.quick_url)
        self.assertEqual(response.status_code, 302)
        still = self.get(self.release_url)
        self.assertFalse(still.context['stats']['company_identity_missing'])
        self.assertFalse(still.context['stats']['company_tech_missing'])
        self.assertEqual(still.context['stats']['copyright_missing'], 1)
        self.assertEqual(still.context['stats']['classification_missing'], 1)
        self.assertEqual(still.context['eligible_count'], 0)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_can_verify_only_identity_and_no_unchecked_claims(self):
        page = self.get(self.quick_url)
        result = self.post(self.quick_url, self.data(page, tech=False),
                           HTTP_REFERER='https://jobiew.ir' + self.quick_url)
        self.assertEqual(result.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.identity_status, 'verified')
        self.assertEqual(self.company.tech_status, 'unverified')
        self.assertEqual(CompanyVerificationEvent.objects.count(), 1)

    def test_empty_or_unattested_form_never_approves(self):
        page = self.get(self.quick_url)
        for edit in [
            {'confirm_evidence': ''},
            {'evidence_url': ''},
            {'evidence_url': 'http://insecure.example.invalid'},
            {'verify_identity': '', 'verify_tech': ''},
        ]:
            with self.subTest(edit=edit):
                invalid = {**self.data(page), **edit}
                result = self.post(self.quick_url, invalid,
                                   HTTP_REFERER='https://jobiew.ir' + self.quick_url)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(CompanyVerificationEvent.objects.count(), 0)
        bad_origin = self.post(self.quick_url, self.data(page),
                               HTTP_ORIGIN='https://malicious.invalid')
        self.assertEqual(bad_origin.status_code, 403)
        self.assertFalse(CompanyVerificationEvent.objects.exists())

    def test_rejects_stale_form_without_overwriting_existing_event(self):
        page = self.get(self.quick_url)
        CompanyVerificationEvent.objects.create(
            company=self.company, reviewer=self.admin, field='identity',
            decision='rejected', rationale='اطلاعات منبع قبلی هنوز قابل اتکا نیست.',
            evidence_url='')
        response = self.post(self.quick_url, self.data(page),
                             HTTP_REFERER='https://jobiew.ir' + self.quick_url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CompanyVerificationEvent.objects.count(), 1)
        self.company.refresh_from_db()
        self.assertNotEqual(self.company.identity_status, 'verified')
