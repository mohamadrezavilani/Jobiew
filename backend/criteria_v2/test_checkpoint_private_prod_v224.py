"""Private production import and deliberate, auditable company publication (synthetic only)."""
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.models import (
    CriteriaAnalysis, CriteriaReviewEvent, CriteriaScoreReviewEvent,
    CriteriaCompanyReleaseEvent)
from criteria_v2.registry import axes_for, version_for
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.management.commands.stage_checkpoint_private_prod_v224 import guard_private_production
from criteria_v2.sufficiency_v208 import company_public_sufficiency

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
    'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '0',
    'JOBIEW_COMPANY_RELEASE_ONLY_ENABLED': '1',
}
BODY = ('حقوق ماهانه طبق توافق بدون تاخیر پرداخت شد و قرارداد کتبی روشن بود. '
        'در سایر موضوعات اطلاعات دقیقی ندارم.')
QUOTE = 'حقوق ماهانه طبق توافق بدون تاخیر پرداخت شد'


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['jobiew.ir', 'testserver'])
class PrivateProductionReleaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='v224-company', source_url='https://example.invalid/v224/company',
            source_name='synthetic', display_name='شرکت ساختگی انتشار',
            identity_status='verified', tech_status='verified')
        cls.staff = get_user_model().objects.create_superuser(
            username='v224-manager', email='v224@example.invalid', password='test-only')
        cls.ordinary = get_user_model().objects.create_user(
            username='v224-visitor', password='test-only')
        cls.exps = []
        for i in range(2):
            body = BODY + (' تجربه شماره ' + str(i))
            cls.exps.append(PublicExperience.objects.create(
                company=cls.company,
                source_url='https://example.invalid/v224/story/' + str(i),
                title='ساختگی', body=body, source_kind='work',
                content_sha256=hashlib.sha256(body.encode()).hexdigest()))

    def proposal(self, exp):
        axes = axes_for('work')
        dims = {
            axis.key: ({
                'score': 8, 'confidence': 88,
                'evidence': QUOTE,
                'explanation': 'پرداخت حقوق با شاهد دقیق و قابل بررسی تایید شد'
            } if i == 0 else {
                'score': None, 'confidence': 0, 'evidence': '',
                'explanation': 'متن تجربه درباره این معیار شاهد مناسبی ندارد'
            }) for i, axis in enumerate(axes)}
        return {
            'experience_id': exp.pk, 'company_id': exp.company_id,
            'kind': exp.source_kind, 'source_content_sha256': exp.content_sha256,
            'story_sha256': story_digest(story_from_experience(exp)),
            'review_status': 'unverified_private_proposal',
            'model_name': 'GPT-6-synthetic',
            'prediction': {
                'detected_kind': 'work', 'kind_confidence': 91, 'dimensions': dims,
            },
        }

    def stage(self):
        for exp in self.exps:
            self.assertTrue(stage_one(self.proposal(exp)))

    def as_staff(self):
        self.client.force_login(self.staff)

    def private_get(self, url):
        with patch.dict('os.environ', FLAGS):
            return self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')

    def private_post(self, url, data):
        with patch.dict('os.environ', FLAGS):
            return self.client.post(url, data, secure=True, HTTP_HOST='jobiew.ir')

    def review_all(self):
        self.as_staff()
        url = reverse('dual-checkpoint-bulk-v222', args=[self.company.pk])
        page = self.private_get(url)
        self.assertEqual(page.status_code, 200)
        data = {
            'snapshot': page.context['token'],
            'ready_count': str(page.context['ready_count']),
            'selected': [str(row['run'].pk) for row in page.context['rows']
                         if not row['reason']],
            'confirm_reviewed': 'yes', 'confirm_private': 'yes',
            'note': 'روایت‌ها و شواهد مربوط به پرداخت حقوق را به دقت بررسی کردم.',
        }
        response = self.private_post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 2)

    def clear_provenance(self, exp):
        CriteriaReviewEvent.objects.create(
            experience=exp, reviewer=self.staff,
            source_kind=exp.source_kind, criteria_version=version_for(exp.source_kind),
            source_content_sha256=exp.content_sha256, decision='confirmed')
        for field, decision in [('copyright', 'approved'),
                                ('attribution', 'verified'),
                                ('independence', 'verified')]:
            ExperienceReviewEvent.objects.create(
                experience=exp, review_field=field, decision=decision,
                evidence_url='https://example.invalid/source/license-and-verification',
                rationale='بازبینی مستقل مستند در محیط تست با منبع ساختگی.',
                reviewer=self.staff)

    def release(self, action='published'):
        url = reverse('dual-company-release-v224', args=[self.company.pk])
        page = self.private_get(url)
        self.assertEqual(page.status_code, 200)
        data = {
            'snapshot': page.context['token'], 'action': action,
            'confirm_rights': 'yes', 'confirm_public': 'yes',
            'note': 'بازبینی اسناد و کیفیت امتیازهای شش‌محوری این شرکت انجام شد.',
        }
        return self.private_post(url, data)

    def test_private_review_requires_https_public_host_and_staff(self):
        self.stage()
        url = reverse('dual-checkpoint-dashboard-v218')
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST='jobiew.ir').status_code, 403)
            self.client.force_login(self.ordinary)
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST='jobiew.ir').status_code, 403)
            self.as_staff()
            self.assertEqual(self.client.get(url, HTTP_HOST='jobiew.ir').status_code, 404)
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST='testserver').status_code, 404)
            ok = self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')
            self.assertEqual(ok.status_code, 200)
            self.assertIn('no-store', ok['Cache-Control'])
            self.assertIn('noindex', ok['X-Robots-Tag'])

    def test_review_without_provenance_cannot_publish(self):
        self.stage()
        self.review_all()
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 0)
        self.assertEqual(self.release().status_code, 409)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_explicit_release_only_affects_reviewed_and_rights_cleared(self):
        self.stage()
        self.review_all()
        self.clear_provenance(self.exps[0])
        self.clear_provenance(self.exps[1])
        public = {**FLAGS, 'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1',
                  'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED':'1'}
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 0)
        self.assertEqual(self.release().status_code, 302)
        with patch.dict('os.environ', public):
            data = company_public_sufficiency(self.company)
            self.assertEqual(data['work']['axes'][0]['dimension_experience_count'], 2)
            self.assertEqual(data['work']['axes'][0]['score'], 8.0)
            self.assertEqual(data['interview']['axes'][0]['dimension_experience_count'], 0)
            response = self.client.get(reverse('company-detail', args=[self.company.pk])+'?tab=ai')
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, BODY)
        event = CriteriaCompanyReleaseEvent.objects.get()
        self.assertEqual(event.reviewer_id, self.staff.pk)
        self.assertEqual(len(event.approved_runs), 2)
        with self.assertRaises(ValueError):
            event.delete()
        self.assertEqual(self.release(action='held').status_code, 302)
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 0)

    def test_single_company_release_not_another_and_rights_reversal(self):
        self.stage()
        self.review_all()
        for exp in self.exps:
            self.clear_provenance(exp)
        self.assertEqual(self.release().status_code, 302)
        public = {**FLAGS, 'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1',
                  'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED':'1'}
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 2)
        # An appended later source legal hold immediately removes one score.
        ExperienceReviewEvent.objects.create(
            experience=self.exps[0], review_field='copyright', decision='blocked',
            evidence_url='', rationale='منبع جدیداً با وضعیت حقوقی مسدود شد.',
            reviewer=self.staff)
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 1)

    def test_new_private_scores_require_separate_release_event(self):
        self.stage()
        self.review_all()
        self.clear_provenance(self.exps[0])
        self.assertEqual(self.release().status_code, 302)
        events = CriteriaCompanyReleaseEvent.objects.count()
        self.assertEqual(events, 1)
        # Rights of another already reviewed record become valid later; no auto-release.
        self.clear_provenance(self.exps[1])
        public = {**FLAGS, 'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1',
                  'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED':'1'}
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 1)
        self.assertEqual(self.release().status_code, 302)
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 2)

    def test_ineligible_source_or_edited_score_fails_closed(self):
        self.stage()
        self.review_all()
        for exp in self.exps:
            self.clear_provenance(exp)
        self.assertEqual(self.release().status_code, 302)
        analysis = CriteriaAnalysis.objects.get(experience=self.exps[0])
        analysis.axis_scores.filter(score__isnull=False).update(score=1)
        public = {**FLAGS, 'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1',
                  'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED':'1'}
        with patch.dict('os.environ', public):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 1)

    def test_release_never_auto_sets_source_legal_status(self):
        self.stage()
        self.review_all()
        self.assertEqual(self.release().status_code, 409)
        for exp in self.exps:
            exp.refresh_from_db()
            self.assertEqual(exp.copyright_review, 'pending')
            self.assertEqual(exp.company_attribution_status, 'unverified')

    def test_release_rejects_snapshot_replay(self):
        self.stage()
        self.review_all()
        self.clear_provenance(self.exps[0])
        self.as_staff()
        url = reverse('dual-company-release-v224', args=[self.company.pk])
        original = self.private_get(url)
        token = original.context['token']
        self.clear_provenance(self.exps[1])
        bad = self.private_post(url, {
            'snapshot': token, 'action': 'published',
            'confirm_public':'yes', 'confirm_rights':'yes',
            'note':'درخواست قدیمی انتشار شرکت دیگر معتبر نیست.'})
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())


@override_settings(DEBUG=False, ALLOWED_HOSTS=['jobiew.ir', 'testserver'])
class PrivateProductionImportGuardTests(TestCase):
    def test_guard_only_postgresql_exact_db_private_and_no_publication(self):
        cfg = {'ENGINE':'django.db.backends.postgresql', 'NAME':'jobiew',
               'HOST':'127.0.0.1'}
        flags = {**FLAGS, 'JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED':'1'}
        with patch('criteria_v2.management.commands.stage_checkpoint_private_prod_v224.connection',
                   SimpleNamespace(settings_dict=cfg)), patch.dict('os.environ', flags):
            self.assertEqual(guard_private_production('jobiew'), 'jobiew')
            with self.assertRaises(CommandError):
                guard_private_production('other')
        for override in (
            {'JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED':'0'},
            {'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED':'0'},
            {'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1'},
            {'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED':'1'},
            {'JOBIEW_COMPANY_RELEASE_ONLY_ENABLED':'0'},
            {'JOBIEW_CHECKPOINT_STAGING_ENABLED':'1'},
        ):
            with patch('criteria_v2.management.commands.stage_checkpoint_private_prod_v224.connection',
                       SimpleNamespace(settings_dict=cfg)), patch.dict('os.environ', {**flags, **override}):
                with self.assertRaises(CommandError):
                    guard_private_production('jobiew')
        for override in (
            {'NAME':'jobiew_staging'}, {'HOST':'production.internal'},
            {'ENGINE':'django.db.backends.sqlite3'},
        ):
            with patch('criteria_v2.management.commands.stage_checkpoint_private_prod_v224.connection',
                       SimpleNamespace(settings_dict={**cfg, **override})), patch.dict('os.environ', flags):
                with self.assertRaises(CommandError):
                    guard_private_production('jobiew')


class SingleCommandCumulativeImportTests(TestCase):
    """Run the actual one-shot import path on synthetic source/ZIP, never user data."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='synthetic-company',
            source_name='synthetic',
            source_url='https://example.invalid/cumulative-v221',
            display_name='شرکت تست خصوصی')
        cls.exp = PublicExperience.objects.create(
            pk=1, company=cls.company,
            source_url='https://example.invalid/cumulative-v221/e1',
            source_kind='work',
            title='عنوان محرمانهٔ ساختگی',
            body='یک روایت ساختگی صرفاً برای تست اعتبارسنجی فرمت و نقل قول.',
            content_sha256='a' * 64)

    def test_full_archive_preflight_then_idempotent_private_write(self):
        import json
        import tempfile
        from pathlib import Path
        from io import StringIO
        from django.core.management import call_command
        from criteria_v2.test_checkpoint_cumulative_v221 import synthetic, archive, SOURCE_SHA
        from criteria_v2.management.commands.stage_checkpoint_private_prod_v224 import Command
        payload = synthetic()
        ledger = [json.loads(line) for line in payload['ledger.jsonl'].splitlines()]
        first = json.loads(payload['assistant_predictions.jsonl'])
        digest = story_digest(story_from_experience(self.exp))
        ledger[0]['story_sha256'] = digest
        first['story_sha256'] = digest
        payload['ledger.jsonl'] = b'\n'.join(
            json.dumps(row, ensure_ascii=False).encode() for row in ledger)
        payload['assistant_predictions.jsonl'] = json.dumps(
            first, ensure_ascii=False).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic-checkpoint.zip'
            checksum = archive(path, payload)
            args = {
                'checkpoint': str(path), 'expected_db': 'jobiew',
                'expected_checkpoint_sha256': checksum,
                'expected_source_sha256': SOURCE_SHA, 'all_batches': True,
                'max_total': 3000, 'limit': 100,
            }
            with patch.object(Command, 'guard_database', return_value='jobiew'):
                output = StringIO()
                call_command('stage_checkpoint_private_prod_v224',
                             stdout=output, **args)
                self.assertIn('DRY_RUN_READ_ONLY', output.getvalue())
                self.assertEqual(CriteriaAnalysis.objects.count(), 0)
                output = StringIO()
                call_command('stage_checkpoint_private_prod_v224',
                             stdout=output, apply=True,
                             acknowledge_unverified_private_data=True, **args)
                self.assertIn('PRIVATE_STAGE_UNVERIFIED', output.getvalue())
                self.assertEqual(CriteriaAnalysis.objects.count(), 1)
                self.assertEqual(CriteriaAnalysis.objects.get().review_status, 'pilot_unverified')
                self.assertFalse(CriteriaScoreReviewEvent.objects.exists())
                output = StringIO()
                call_command('stage_checkpoint_private_prod_v224',
                             stdout=output, apply=True,
                             acknowledge_unverified_private_data=True, **args)
                self.assertIn('"inserted": 0', output.getvalue())
                self.assertEqual(CriteriaAnalysis.objects.count(), 1)
