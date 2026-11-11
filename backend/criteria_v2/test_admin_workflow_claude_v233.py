"""v233: task-first admin and independent six-axis Claude tests, synthetic data only."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import (
    CriteriaAnalysis, CriteriaClaudeComparison,
    CriteriaCompanyReleaseEvent, CriteriaScoreReviewEvent)
from criteria_v2.registry import axes_for
from experiences.models import ExperienceReviewEvent, PublicExperience

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1',
    'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '1',
    'JOBIEW_COMPANY_RELEASE_ONLY_ENABLED': '1',
    'JOBIEW_CLAUDE_SIX_ENABLED': '1',
    'JOBIEW_CLAUDE_SIX_LIMIT': '4',
    'JOBIEW_CLAUDE_SIX_MODEL': 'claude-sonnet-5-5',
    'ANTHROPIC_API_KEY': 'synthetic-never-sent',
}
BODY = ('پرداخت حقوق در شرکت شفاف بود و همکاران تجربهٔ همکاری محترمانه‌ای داشتند. '
        'من فقط دربارهٔ تجربهٔ کاری خودم گزارش می‌دهم و برای مسائل دیگر شاهدی ندارم.')
QUOTE = 'پرداخت حقوق در شرکت شفاف بود'


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['jobiew.ir', 'testserver'],
                   CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class TaskFirstAdminV233Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.co = Company.objects.create(
            id='v233-example', source_name='synthetic',
            source_url='https://example.invalid/co', display_name='شرکت نمایشی ۲۳۳',
            identity_status='verified', tech_status='verified')
        cls.staff = get_user_model().objects.create_superuser(
            username='admin-v233', password='test-only',
            email='admin-v233@example.invalid')
        cls.exp = PublicExperience.objects.create(
            company=cls.co, source_kind='work',
            source_url='https://example.invalid/story',
            title='تجربهٔ آزمایشی', body=BODY, content_sha256='e'*64)
        axes = axes_for('work')
        dimensions = {
            axis.key: (
                {'score': 8, 'confidence': 86, 'evidence': QUOTE,
                 'explanation': 'شاهد واضح دربارهٔ پرداخت منظم و شفاف است.'}
                if i == 0 else
                {'score': None, 'confidence': 0, 'evidence': '',
                 'explanation': 'برای این بخش شاهد مستقیم کافی وجود ندارد.'}
            ) for i, axis in enumerate(axes)
        }
        stage_one({
            'experience_id': cls.exp.pk, 'company_id': cls.co.pk,
            'kind': 'work', 'source_content_sha256': cls.exp.content_sha256,
            'story_sha256': story_digest(story_from_experience(cls.exp)),
            'model_name': 'GPT-6-synthetic-v233',
            'review_status': 'unverified_private_proposal',
            'prediction': {
                'detected_kind': 'work', 'kind_confidence': 95,
                'dimensions': dimensions,
            },
        })

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.staff)
        self.workflow = reverse('admin:companies_company_workflow', args=[self.co.pk])
        self.detail = reverse('admin:companies_company_experience_detail',
                              args=[self.co.pk, self.exp.pk])
        self.claude = reverse('admin:companies_company_experience_claude',
                              args=[self.co.pk, self.exp.pk])
        self.index = reverse('admin:index')
        self.list = reverse('admin:companies_company_experiences', args=[self.co.pk])

    def get(self, url, flags=None):
        with patch.dict('os.environ', FLAGS if flags is None else flags):
            return self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')

    def post(self, url, data):
        with patch.dict('os.environ', FLAGS):
            return self.client.post(
                url, data, secure=True, HTTP_HOST='jobiew.ir',
                HTTP_REFERER='https://jobiew.ir' + url)

    def test_home_queue_and_workflow_have_one_clear_next_action(self):
        home = self.get(self.index)
        self.assertContains(home, 'میز کار شرکت‌ها')
        self.assertContains(home, 'امکانات فنی و تاریخچهٔ حسابرسی')
        workflow = self.get(self.workflow)
        self.assertEqual(workflow.status_code, 200)
        self.assertEqual(workflow.context['next_step'], 'scores')
        self.assertEqual(workflow.context['summary']['pending'], 1)
        self.assertContains(workflow, '۱. تجربه‌ها و مصاحبه‌ها')
        self.assertContains(workflow, 'بررسی همین پرونده‌های باقی‌مانده')
        listing = self.get(self.list)
        self.assertContains(listing, 'بررسی اختیاری با Claude')
        self.assertContains(listing, self.claude)
        detail = self.get(self.detail)
        self.assertContains(detail, 'بررسی با Claude و مشاهدهٔ نتیجه')
        self.assertContains(detail, self.workflow)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_claude_is_never_called_on_get_and_no_legacy_five_axes(self):
        with patch('companies.claude_six_v233.call_claude') as paid:
            page = self.get(self.claude)
        paid.assert_not_called()
        self.assertContains(page, 'شش معیار')
        self.assertContains(page, 'برای این تحلیل هنوز بررسی Claude ثبت نشده است')
        self.assertNotContains(page, 'مقایسهٔ پنج شاخص')
        self.assertFalse(CriteriaClaudeComparison.objects.exists())

    @patch('companies.claude_six_v233.call_claude')
    def test_claude_needs_only_paid_confirmation_not_publication_rights(self, paid):
        """A valid private 6+6 analysis can be independently reviewed without a publication-rights event."""
        dims = {
            axis.key: {
                'score': 7 if i == 0 else None,
                'confidence': 90 if i == 0 else 0,
                'evidence': QUOTE if i == 0 else '',
                'explanation': 'شاهد در متن وجود دارد و این ارزیابی مستقل است.'
            } for i, axis in enumerate(axes_for('work'))
        }
        paid.return_value = {
            'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': json.dumps({
                'detected_kind': 'work', 'kind_confidence': 94,
                'dimensions': dims}, ensure_ascii=False)}],
            'usage': {'input_tokens': 111, 'output_tokens': 222},
        }
        self.get(self.claude)
        with patch('companies.claude_six_v233.call_claude') as not_called:
            missing = self.post(self.claude, {
                'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value})
        self.assertEqual(missing.status_code, 302)
        not_called.assert_not_called()
        self.assertFalse(ExperienceReviewEvent.objects.exists())
        result = self.post(self.claude, {
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
            'confirm_paid': 'yes'})
        self.assertEqual(result.status_code, 302)
        paid.assert_called_once()
        saved = CriteriaClaudeComparison.objects.get()
        self.assertEqual(saved.status, 'completed')
        self.assertEqual(saved.input_tokens, 111)
        self.assertFalse(ExperienceReviewEvent.objects.exists())

    @patch('companies.claude_six_v233.call_claude')
    def test_one_explicit_run_is_saved_and_rendered_but_does_not_publish(self, paid):
        dims = {
            a.key: {
                'score': 7 if i == 0 else None,
                'confidence': 90 if i == 0 else 0,
                'evidence': QUOTE if i == 0 else '',
                'explanation': 'شاهد در متن وجود دارد و این نتیجه مستقل ثبت می‌شود.'
            } for i, a in enumerate(axes_for('work'))
        }
        paid.return_value = {
            'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': json.dumps({
                'detected_kind': 'work', 'kind_confidence': 94,
                'dimensions': dims}, ensure_ascii=False)}],
            'usage': {'input_tokens': 200, 'output_tokens': 360},
        }
        page = self.get(self.claude)
        self.assertEqual(page.status_code, 200)
        result = self.post(self.claude, {
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
            'confirm_paid': 'yes', 'confirm_external_rights': 'yes'})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(CriteriaClaudeComparison.objects.count(), 1)
        record = CriteriaClaudeComparison.objects.get()
        self.assertEqual(record.status, 'completed')
        self.assertEqual(record.input_tokens, 200)
        self.assertEqual(record.claude_axes[axes_for('work')[0].key]['score'], 7)
        self.assertEqual(len(record.claude_axes), 6)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 0)
        self.assertEqual(CriteriaCompanyReleaseEvent.objects.count(), 0)
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'pilot_unverified')
        again = self.post(self.claude, {
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
            'confirm_paid': 'yes', 'confirm_external_rights': 'yes'})
        self.assertEqual(again.status_code, 302)
        paid.assert_called_once()
        view = self.get(self.claude)
        self.assertContains(view, 'مقایسهٔ شش معیار')
        self.assertContains(view, 'نتیجهٔ بررسی مستقل Claude')
        self.assertContains(self.get(self.detail), 'مشاهدهٔ نتیجهٔ Claude')
        self.assertContains(self.get(self.list), 'تکمیل‌شده')
        self.assertNotContains(view, 'پنج شاخص')

    @patch('companies.claude_six_v233.call_claude')
    def test_disabled_default_or_bad_origin_does_not_incur_paid_call(self, paid):
        self.get(self.claude)
        disabled = {**FLAGS, 'JOBIEW_CLAUDE_SIX_ENABLED': '0'}
        with patch.dict('os.environ', disabled):
            result = self.client.post(self.claude, {
                'confirm_paid': 'yes',
                'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value},
                secure=True, HTTP_HOST='jobiew.ir',
                HTTP_REFERER='https://jobiew.ir' + self.claude)
        self.assertEqual(result.status_code, 302)
        self.assertFalse(CriteriaClaudeComparison.objects.exists())
        origin = self.client.post(self.claude, {
            'confirm_paid': 'yes',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value},
            secure=True, HTTP_HOST='jobiew.ir', HTTP_ORIGIN='https://evil.invalid')
        self.assertEqual(origin.status_code, 403)
        self.assertFalse(CriteriaClaudeComparison.objects.exists())
        paid.assert_not_called()

    def test_legacy_claude_results_not_mixed_with_six_framework(self):
        from assessments.models import AiAssessment
        from assessments.claude_validation_models_v111 import ClaudeValidationRun
        historical = AiAssessment.objects.create(
            experience=self.exp, criteria_version='five_v1',
            run_id='v233-legacy', prompt_version='legacy', model_name='historical')
        ClaudeValidationRun.objects.create(
            assessment=historical, requested_by=self.staff,
            model_id='claude-historical', source_sha256='a'*64,
            status='completed')
        detail = self.get(self.detail)
        self.assertContains(detail, 'نتیجهٔ تاریخی Claude با پنج معیار قدیمی')
        self.assertContains(detail, reverse(
            'admin:assessments_aiassessment_claude_detail', args=[historical.pk]))
        self.assertNotContains(detail, 'five_v1')
        self.assertNotContains(detail, 'صحت‌سنجی با Claude و مقایسهٔ پنج شاخص')
        self.assertContains(detail, self.claude)


    @patch('companies.claude_six_v233.call_claude')
    def test_claude_needs_review_exposes_outcome_without_fabricating_scores(self, paid):
        """A paid mismatch must remain visible with zero published or accepted axes."""
        paid.return_value = {
            'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': json.dumps({
                'detected_kind': 'interview',
                'kind_confidence': 91,
                'dimensions': {},
            })}],
            'usage': {'input_tokens': 123, 'output_tokens': 45},
        }
        self.get(self.claude)
        out = self.post(self.claude, {
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value,
            'confirm_paid': 'yes', 'confirm_external_rights': 'yes',
        })
        self.assertEqual(out.status_code, 302)
        result = CriteriaClaudeComparison.objects.get()
        self.assertEqual(result.status, 'needs_review')
        self.assertEqual(result.claude_axes, {})
        page = self.get(self.claude)
        self.assertContains(page, 'نوع تشخیص‌داده‌شده توسط Claude')
        self.assertContains(page, 'interview')
        self.assertContains(page, 'توکن ورودی')
        self.assertContains(page, '123')
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())
        paid.assert_called_once()
