"""Synthetic 6+6 source-checklist regression on real Django CSRF and DB logic."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import (
    CriteriaAnalysis, CriteriaReviewEvent, CriteriaScoreReviewEvent,
    CriteriaCompanyReleaseEvent)
from criteria_v2.registry import axes_for
from experiences.models import PublicExperience, ExperienceReviewEvent

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1',
    'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '1',
    'JOBIEW_COMPANY_RELEASE_ONLY_ENABLED': '1',
}
STORY = ('پرداخت حقوق مرتب بوده و در قرارداد نیز تاریخ پرداخت ذکر شده بود. '
         'از ابعاد دیگر تجربهٔ مشخصی ندارم.')
QUOTE = 'پرداخت حقوق مرتب بوده'


@override_settings(
    DEBUG=False, SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['jobiew.ir', 'testserver'],
    CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class ProvenanceBulkV228Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='group-v228', source_name='synthetic',
            source_url='https://example.invalid/group', display_name='شرکت گروهی',
            identity_status='verified', tech_status='verified')
        cls.other = Company.objects.create(
            id='group-other-v228', source_name='synthetic',
            source_url='https://example.invalid/other',
            display_name='شرکت دیگر')
        cls.staff = get_user_model().objects.create_superuser(
            username='review-v228', email='review-v228@example.invalid',
            password='not-a-real-password')
        cls.exp = []
        for i in range(2):
            body = STORY + str(i)
            exp = PublicExperience.objects.create(
                company=cls.company, source_kind='work',
                source_url='https://example.invalid/story-' + str(i),
                source_site='example.invalid',
                title='تجربهٔ ساختگی ' + str(i), body=body,
                content_sha256=('%064x' % (i + 1)))
            cls.exp.append(exp)
            axes = axes_for(exp.source_kind)
            dimensions = {
                axis.key: (
                    {'score': 8, 'confidence': 85, 'evidence': QUOTE,
                     'explanation': 'شاهد پرداخت منظم و به‌موقع گزارش شده'}
                    if pos == 0 else
                    {'score': None, 'confidence': 0, 'evidence': '',
                     'explanation': 'برای این معیار در متن شاهد کافی وجود ندارد'}
                ) for pos, axis in enumerate(axes)
            }
            stage_one({
                'experience_id': exp.pk, 'company_id': exp.company_id,
                'kind': exp.source_kind,
                'source_content_sha256': exp.content_sha256,
                'story_sha256': story_digest(story_from_experience(exp)),
                'review_status': 'unverified_private_proposal',
                'model_name': 'GPT-6-synthetic-v228',
                'prediction': {'detected_kind': exp.source_kind,
                               'kind_confidence': 89, 'dimensions': dimensions},
            })
        cls.foreign = PublicExperience.objects.create(
            company=cls.other, source_kind='work',
            source_url='https://example.invalid/foreign',
            title='بدنه محرمانه شرکت دیگر', body='خاص شرکت دیگر',
            content_sha256='f'*64)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.staff)
        self.url = reverse('admin:companies_company_checkpoint_sources',
                           args=[self.company.pk])
        self.bulk = reverse('admin:companies_company_checkpoint_bulk',
                            args=[self.company.pk])
        self.release = reverse('admin:companies_company_checkpoint_release',
                               args=[self.company.pk])
        self._approve_scores()

    def get(self, url=None, flags=None):
        with patch.dict('os.environ', flags or FLAGS):
            return self.client.get(url or self.url, secure=True,
                                   HTTP_HOST='jobiew.ir')

    def post(self, data, url=None, origin=None):
        kwargs = {'HTTP_HOST': 'jobiew.ir'}
        if origin is None:
            kwargs['HTTP_REFERER'] = 'https://jobiew.ir' + (url or self.url)
        else:
            kwargs['HTTP_ORIGIN'] = origin
        with patch.dict('os.environ', FLAGS):
            return self.client.post(url or self.url, data,
                                    secure=True, **kwargs)

    def _approve_scores(self):
        page = self.get(self.bulk)
        self.assertEqual(page.status_code, 200)
        result = self.post({
            'snapshot': page.context['token'],
            'ready_count': str(page.context['ready_count']),
            'selected': [str(row['run'].pk) for row in page.context['rows']
                         if not row['reason']],
            'confirm_reviewed': 'yes', 'confirm_private': 'yes',
            'note': 'شواهد هر محور در روایات مصنوعی مستقل بررسی شده‌اند.',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
        }, url=self.bulk)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 2)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def form(self, page, *, action='standard', selected=None, doc='',
             scope='standard', note=''):
        return {
            'snapshot': page.context['snapshot'],
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
            'selected': [str(exp.pk) for exp in self.exp] if selected is None else selected,
            'action': action,
            'scope': scope,
            'note': note,
            'confirm_manual': 'yes',
            'rights_document_url': doc,
        }

    def test_real_csrf_get_works_and_invalid_origin_blocks(self):
        page = self.get()
        self.assertEqual(page.status_code, 200)
        self.assertIn('csrftoken', self.client.cookies)
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        self.assertContains(page, 'منبع اصلی')
        self.assertContains(page, self.release)
        self.assertContains(page, 'name="selected"', count=2)
        self.assertContains(page, 'checked', count=2)
        self.assertContains(page, 'ثبت بررسی‌های عادی (بدون تأیید مجوز انتشار)')
        self.assertNotContains(page, 'EXPLICIT_RIGHTS_DOCUMENT_REQUIRED')
        result = self.post(self.form(page), origin='https://evil.invalid')
        self.assertEqual(result.status_code, 403)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        self.assertFalse(CriteriaReviewEvent.objects.exists())

    def test_group_review_without_licence_does_not_unlock_publication(self):
        page = self.get()
        response = self.post(self.form(page))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.release)
        self.assertEqual(ExperienceReviewEvent.objects.count(), 4)
        self.assertEqual(CriteriaReviewEvent.objects.count(), 2)
        for exp in self.exp:
            exp.refresh_from_db()
            self.assertEqual(exp.company_attribution_status, 'verified')
            self.assertEqual(exp.independence_status, 'verified')
            self.assertEqual(exp.copyright_review, 'pending')
        release = self.get(self.release)
        self.assertEqual(release.context['eligible_count'], 0)
        self.assertEqual(release.context['stats']['copyright_missing'], 2)
        self.assertEqual(release.context['stats']['classification_missing'], 0)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_independent_rights_document_then_explicit_company_release(self):
        first = self.get()
        self.assertEqual(self.post(self.form(first)).status_code, 302)
        page = self.get()
        data = self.form(
            page, action='rights', doc='https://example.invalid/licence/v228')
        self.assertEqual(self.post(data).status_code, 302)
        self.assertEqual(ExperienceReviewEvent.objects.count(), 6)
        for exp in self.exp:
            exp.refresh_from_db()
            self.assertEqual(exp.copyright_review, 'approved')
        ready = self.get(self.release)
        self.assertEqual(ready.context['eligible_count'], 2)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())
        posted = self.post({
            'snapshot': ready.context['token'],
            'action': 'published',
            'confirm_rights': 'yes', 'confirm_public': 'yes',
            'note': 'پس از مستند کردن حقوق و صحت امتیازها تصمیم انتشار گرفته شد.',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
        }, url=self.release)
        self.assertEqual(posted.status_code, 302)
        event = CriteriaCompanyReleaseEvent.objects.get()
        self.assertEqual(event.decision, 'published')
        self.assertEqual(len(event.approved_runs), 2)

    def test_no_licence_url_or_same_story_url_never_approves_rights(self):
        for url in (
            '', 'http://example.invalid/rights',
            self.exp[0].source_url, 'javascript:alert(1)',
        ):
            with self.subTest(url=url):
                page = self.get()
                result = self.post(self.form(page,
                    action='rights', selected=[str(self.exp[0].pk)], doc=url))
                self.assertEqual(result.status_code, 400)
                self.assertContains(result, 'ثبت انجام نشد', status_code=400)
                self.assertContains(result, 'checked', count=1, status_code=400)
                self.assertFalse(ExperienceReviewEvent.objects.exists())
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_selected_foreign_experience_and_empty_selection_rejected(self):
        page = self.get()
        bad = self.post(self.form(page, selected=[str(self.foreign.pk)]))
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        empty = self.post(self.form(page, selected=[]))
        self.assertEqual(empty.status_code, 400)
        self.assertFalse(CriteriaReviewEvent.objects.exists())

    def test_disabled_private_view_fails_closed(self):
        disabled = {**FLAGS, 'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '0'}
        response = self.get(flags=disabled)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExperienceReviewEvent.objects.exists())

    def test_stale_snapshot_rejected_before_any_write(self):
        page = self.get()
        ExperienceReviewEvent.objects.create(
            experience=self.exp[0], review_field='attribution', decision='rejected',
            evidence_url='', rationale='انتساب به شرکت موردنظر رد شد.',
            reviewer=self.staff)
        result = self.post(self.form(page))
        self.assertEqual(result.status_code, 409)
        self.assertEqual(ExperienceReviewEvent.objects.count(), 1)
        self.assertFalse(CriteriaReviewEvent.objects.exists())

    def test_known_blocked_source_is_not_bulk_overridden(self):
        ExperienceReviewEvent.objects.create(
            experience=self.exp[0], review_field='copyright', decision='blocked',
            evidence_url='', rationale='منبع اجازه بازنشر این نظر را نمی‌دهد.',
            reviewer=self.staff)
        page = self.get()
        rows = page.context['rows']
        blocked = next(row for row in rows if row['exp'].pk == self.exp[0].pk)
        self.assertFalse(blocked['eligible'])
        bad = self.post(self.form(page, selected=[str(self.exp[0].pk)]))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(ExperienceReviewEvent.objects.count(), 1)

    def test_invalid_or_unsupported_review_scope_does_not_write(self):
        page = self.get()
        bad = self.post(self.form(page, scope='copyright_without_proof'))
        self.assertEqual(bad.status_code, 400)
        self.assertContains(bad, 'نوع بررسی انتخاب‌شده معتبر نیست', status_code=400)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        self.assertEqual(CriteriaAnalysis.objects.count(), 2)

    def test_default_form_without_note_needs_one_explicit_attestation(self):
        page = self.get()
        data = self.form(page)
        data.pop('confirm_manual')
        blocked = self.post(data)
        self.assertEqual(blocked.status_code, 400)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        result = self.post(self.form(page))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(ExperienceReviewEvent.objects.count(), 4)
        self.assertEqual(CriteriaReviewEvent.objects.count(), 2)
        self.assertEqual(CriteriaCompanyReleaseEvent.objects.count(), 0)

    def test_selected_rows_can_be_unchecked_or_scope_narrowed(self):
        page = self.get()
        data = self.form(
            page, selected=[str(self.exp[1].pk)], scope='classification')
        result = self.post(data)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(CriteriaReviewEvent.objects.count(), 1)
        self.assertEqual(CriteriaReviewEvent.objects.first().experience_id,
                         self.exp[1].pk)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_rights_error_is_friendly_and_preserves_row_selection(self):
        page = self.get()
        result = self.post(self.form(page, action='rights', doc=''))
        self.assertEqual(result.status_code, 400)
        self.assertContains(result, 'برای ثبت مجوز انتشار', status_code=400)
        self.assertContains(result, 'ثبت بررسی‌های عادی', status_code=400)
        self.assertContains(result, 'checked', count=2, status_code=400)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_missing_staff_permissions_restrict_private_reviews(self):
        staff = get_user_model().objects.create_user(
            username='v228-limited', password='test-only', is_staff=True)
        staff.user_permissions.add(
            Permission.objects.get(content_type__app_label='companies',
                                   codename='view_company'))
        self.client.force_login(staff)
        page = self.get()
        self.assertEqual(page.status_code, 403)
        self.assertFalse(ExperienceReviewEvent.objects.exists())
