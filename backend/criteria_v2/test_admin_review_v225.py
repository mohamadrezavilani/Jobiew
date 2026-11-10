"""Synthetic admin-workflow and real CSRF middleware integration tests.

No production checkpoint records or third-party requests are used.
"""
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from experiences.models import PublicExperience
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import CriteriaAnalysis, CriteriaScoreReviewEvent, CriteriaCompanyReleaseEvent
from criteria_v2.registry import axes_for

REVIEW_FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
    'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '0',
    'JOBIEW_ADMIN_FOCUSED_WORKFLOW_ENABLED': '1',
}
TEXT = ('حقوق ماهانه با تاخیر پرداخت می‌شد و قرارداد مکتوب شفاف نبود. '
        'در مورد موضوع‌های دیگر اطلاعات کافی در این روایت وجود ندارد.')
QUOTE = 'حقوق ماهانه با تاخیر پرداخت می‌شد'


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['jobiew.ir', 'testserver'],
                   CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class AdminCheckpointWorkflowV225Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='admin-v225-synthetic', source_url='https://example.invalid/admin-v225',
            source_name='synthetic', display_name='شرکت ساختگی پنل جدید',
            identity_status='verified', tech_status='verified')
        cls.staff = get_user_model().objects.create_superuser(
            username='synthetic-v225-admin', password='never-a-real-password',
            email='synthetic-v225@example.invalid')
        cls.exp = PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.invalid/admin-v225/ex',
            title='دادهٔ ساختگی برای تست', body=TEXT,
            content_sha256='c' * 64)
        dims = {}
        for n, axis in enumerate(axes_for('work')):
            if n == 0:
                dims[axis.key] = {'score': 3, 'confidence': 90, 'evidence': QUOTE,
                    'explanation': 'تأخیر پرداخت حقوق صریحاً در شواهد ثبت شده است'}
            else:
                dims[axis.key] = {'score': None, 'confidence': 0, 'evidence': '',
                    'explanation': 'در روایت برای این معیار شاهد کافی ثبت نشده است'}
        stage_one({
            'experience_id': cls.exp.pk, 'company_id': cls.exp.company_id,
            'kind': 'work', 'source_content_sha256': cls.exp.content_sha256,
            'story_sha256': story_digest(story_from_experience(cls.exp)),
            'review_status': 'unverified_private_proposal',
            'model_name': 'gpt-6-synthetic-not-external',
            'prediction': {'detected_kind':'work', 'kind_confidence':90, 'dimensions':dims},
        })

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.staff)
        self.bulk = reverse('admin:companies_company_checkpoint_bulk', args=[self.company.pk])
        self.release = reverse('admin:companies_company_checkpoint_release', args=[self.company.pk])
        self.queue = reverse('admin:companies_company_checkpoint_queue')

    def get(self, url):
        with patch.dict('os.environ', REVIEW_FLAGS):
            return self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')

    def post(self, url, data, **headers):
        with patch.dict('os.environ', REVIEW_FLAGS):
            return self.client.post(url, data, secure=True,
                                    HTTP_HOST='jobiew.ir', **headers)

    def review_form(self, page):
        return {
            'snapshot': page.context['token'],
            'ready_count': str(page.context['ready_count']),
            'selected': [str(item['run'].pk) for item in page.context['rows']
                         if not item['reason']],
            'confirm_reviewed': 'yes',
            'confirm_private': 'yes',
            'note': 'شواهد و متن روایت ساختگی را معیار به معیار بررسی کرده‌ام.',
        }

    def test_focused_index_shows_current_tasks_without_erasing_legacy_models(self):
        page = self.get(reverse('admin:index'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'بررسی، تأیید و انتشار شرکت‌ها')
        labels = {app['app_label'] for app in page.context['app_list']}
        self.assertIn('companies', labels)
        self.assertIn('experiences', labels)
        self.assertNotIn('assessments', labels)
        self.assertNotIn('voting', labels)
        # Legacy admin URLs still exist: hidden from menu != deleted.
        self.assertIsNotNone(reverse('admin:assessments_aiassessment_changelist'))

    def test_admin_queue_and_company_bulk_links(self):
        queue = self.get(self.queue)
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, self.company.display_name)
        self.assertContains(queue, self.bulk)
        self.assertContains(queue, self.release)
        self.assertEqual(queue.context['page'].paginator.count, 1)
        details = self.get(reverse('admin:companies_company_change',
                                   args=[self.company.pk]))
        self.assertEqual(details.status_code, 200)
        self.assertContains(details, self.bulk)
        self.assertContains(details, self.release)

    def test_real_csrf_missing_cookie_blocks_writes_then_valid_form_works(self):
        # Fresh logged-in browser: a raw POST is correctly rejected.
        url = self.bulk
        bad = self.post(url, {'confirm_private':'yes'}, HTTP_REFERER='https://jobiew.ir'+url)
        self.assertEqual(bad.status_code, 403)
        self.assertContains(bad, 'COOKIE_NOT_SET', status_code=403)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 0)
        page = self.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="csrfmiddlewaretoken"')
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        self.assertIn('csrftoken', self.client.cookies)
        csrf = self.client.cookies['csrftoken'].value
        result = self.post(url, {**self.review_form(page), 'csrfmiddlewaretoken':csrf},
                           HTTP_REFERER='https://jobiew.ir'+url)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.url, url)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 1)
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'approved')

    def test_wrong_origin_is_rejected_and_no_approval_saved(self):
        page = self.get(self.bulk)
        csrf = self.client.cookies['csrftoken'].value
        result = self.post(self.bulk, {**self.review_form(page),
            'csrfmiddlewaretoken':csrf}, HTTP_ORIGIN='https://evil.invalid')
        self.assertEqual(result.status_code, 403)
        self.assertContains(result, 'ORIGIN_MISMATCH', status_code=403)
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())

    def test_publication_form_is_admin_linked_but_fails_closed_without_rights(self):
        page = self.get(self.release)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="csrfmiddlewaretoken"')
        self.assertContains(page, 'فهرست شرکت‌ها')
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        form = {
            'snapshot': page.context['token'],
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
            'action':'published', 'confirm_rights':'yes', 'confirm_public':'yes',
            'note':'اسناد انتشار منبع باید برای هر تجربه جداگانه تأیید شوند.',
        }
        result = self.post(self.release, form, HTTP_REFERER='https://jobiew.ir'+self.release)
        self.assertEqual(result.status_code, 409)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_disabled_private_access_still_blocks_admin_workflow(self):
        with patch.dict('os.environ', {**REVIEW_FLAGS,
                'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED':'0'}):
            self.assertEqual(self.client.get(self.bulk, secure=True,
                        HTTP_HOST='jobiew.ir').status_code, 404)
            self.assertEqual(self.client.get(self.queue, secure=True,
                        HTTP_HOST='jobiew.ir').status_code, 404)
