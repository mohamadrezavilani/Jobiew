"""Django/PostgreSQL integration tests; mocked external API, no paid calls."""
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from experiences.models import PublicExperience
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore
from criteria_v2.registry import AXES

STORY = ('حقوق همیشه با دو ماه تأخیر پرداخت می‌شد و مدیر درباره پرداخت‌ها هیچ توضیحی '
         'نمی‌داد؛ اما کار تیمی و یادگیری در پروژه‌ها مناسب بود و تجربه ارزشمندی داشتیم.')
QUOTE = 'حقوق همیشه با دو ماه تأخیر پرداخت می‌شد'
MODEL = 'claude-sonnet-4-6'
FLAGS = {'JOBIEW_DUAL6_PAID_ENABLED': '1',
         'JOBIEW_DUAL6_EXTERNAL_TEXT_APPROVED': '1',
         'ANTHROPIC_API_KEY': 'mock-not-real'}


def fake_response(kind='work', detected='work', scored=True):
    rows = {a.key: {'score': None, 'confidence': 0, 'evidence': '',
                     'explanation': 'در این متن شاهد کافی برای امتیازدهی وجود ندارد'}
            for a in AXES[kind]}
    if scored:
        rows['work_compensation_fairness'] = {
            'score': 2, 'confidence': 90, 'evidence': QUOTE,
            'explanation': 'تأخیر مستمر در پرداخت حقوق نشان‌دهنده شرایط نامطلوب است'}
    return {'stop_reason': 'end_turn', 'content': [{'type': 'text',
            'text': json.dumps({'detected_kind': detected,
                                'kind_confidence': 90, 'dimensions': rows}, ensure_ascii=False)}],
            'usage': {'input_tokens': 100, 'output_tokens': 100}}


class V207DatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='dual_v207_test', source_url='https://example.test/company-v207',
            source_name='Company', display_name='شرکت آزمایشی')
        cls.exp = PublicExperience.objects.create(
            company=cls.company, source_url='https://example.test/work-v207',
            source_kind='work', title='روایت نمونه', body=STORY,
            content_sha256='a' * 64)

    def run_cmd(self, execute=False):
        args = ['--limit', '1']
        if execute:
            args += ['--execute', '--approve-paid-api', '--model', MODEL]
        out = StringIO()
        call_command('score_dual6_v207', *args, stdout=out)
        return out.getvalue()

    def test_preview_never_writes_or_calls_api(self):
        with patch('criteria_v2.management.commands.score_dual6_v207.call_claude') as api:
            result = self.run_cmd()
        self.assertIn('PREVIEW', result)
        self.assertIn('PUBLICATION: DISABLED', result)
        api.assert_not_called()
        self.assertEqual(CriteriaAnalysis.objects.count(), 0)
        self.assertEqual(CriteriaAxisScore.objects.count(), 0)

    @patch.dict('os.environ', FLAGS)
    @patch('criteria_v2.management.commands.score_dual6_v207.call_claude')
    def test_saves_six_proposals_and_is_idempotent(self, api):
        api.return_value = fake_response()
        self.assertIn('SAVED', self.run_cmd(execute=True))
        self.assertEqual(CriteriaAnalysis.objects.count(), 1)
        run = CriteriaAnalysis.objects.get()
        self.assertEqual(run.review_status, 'unreviewed')
        self.assertEqual(run.axis_scores.count(), 6)
        self.assertEqual(run.axis_scores.get(key='work_compensation_fairness').score, 2)
        self.assertFalse(any(x.semantic_status == 'approved' for x in run.axis_scores.all()))
        self.assertNotIn(STORY, json.dumps(run.raw_payload, ensure_ascii=False))
        self.run_cmd(execute=True)
        api.assert_called_once()
        self.assertEqual(CriteriaAnalysis.objects.count(), 1)

    @patch.dict('os.environ', FLAGS)
    @patch('criteria_v2.management.commands.score_dual6_v207.call_claude')
    def test_kind_disagreement_is_never_scored(self, api):
        api.return_value = fake_response(detected='interview')
        self.run_cmd(execute=True)
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'needs_review')
        self.assertEqual(CriteriaAxisScore.objects.count(), 0)

    @patch.dict('os.environ', FLAGS)
    @patch('criteria_v2.management.commands.score_dual6_v207.call_claude')
    def test_paid_failed_call_is_not_silently_retried(self, api):
        api.side_effect = RuntimeError('ANTHROPIC_HTTP_503')
        self.run_cmd(execute=True)
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'failed')
        self.run_cmd(execute=True)
        api.assert_called_once()

    @patch.dict('os.environ', FLAGS)
    @patch('criteria_v2.management.commands.score_dual6_v207.call_claude')
    def test_source_changing_during_paid_call_is_stale(self, api):
        def race(_):
            PublicExperience.objects.filter(pk=self.exp.pk).update(content_sha256='b' * 64)
            return fake_response()
        api.side_effect = race
        self.run_cmd(execute=True)
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'stale')
        self.assertEqual(CriteriaAxisScore.objects.count(), 0)

    @patch.dict('os.environ', FLAGS)
    @patch('criteria_v2.management.commands.score_dual6_v207.call_claude')
    def test_copyright_blocked_is_not_sent_to_model(self, api):
        PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='blocked')
        self.run_cmd(execute=True)
        api.assert_not_called()
        self.assertEqual(CriteriaAnalysis.objects.count(), 0)

    @patch.dict('os.environ', FLAGS)
    @patch('criteria_v2.management.commands.score_dual6_v207.call_claude')
    def test_unreviewed_scores_not_visible_publicly(self, api):
        api.return_value = fake_response()
        self.run_cmd(execute=True)
        res = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, QUOTE)
        self.assertContains(res, 'data-chart-mode="empty"', count=2)

    @patch.dict('os.environ', {'JOBIEW_DUAL6_PAID_ENABLED': '0',
                               'JOBIEW_DUAL6_EXTERNAL_TEXT_APPROVED': '1',
                               'ANTHROPIC_API_KEY': 'mock-not-real'})
    def test_explicit_pilot_approval_required(self):
        with self.assertRaises(CommandError):
            self.run_cmd(execute=True)
        self.assertEqual(CriteriaAnalysis.objects.count(), 0)
