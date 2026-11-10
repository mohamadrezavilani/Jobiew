"""Synthetic Django tests: company-wide human adjudication, immutable proof and release gates."""
import hashlib
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.management.base import CommandError
from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent
from criteria_v2.models import (CriteriaAnalysis, CriteriaAxisScore, CriteriaScoreReviewEvent,
                                CriteriaReviewEvent, CheckpointApprovalReceipt)
from criteria_v2.engine_v207 import story_from_experience, story_digest
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.registry import axes_for, version_for
from criteria_v2.checkpoint_receipt_v222 import checkpoint_release_ready
from criteria_v2.sufficiency_v208 import company_public_sufficiency
from criteria_v2.management.commands.stage_checkpoint_staging_v222 import guard_dedicated_staging

FLAGS = {'JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED': '1',
         'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
         'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '0'}
TEXT = ('حقوق ماهانه با تاخیر پرداخت می‌شد و مدیر شرکت دربارهٔ تغییرات قرارداد '
        'پاسخ مناسبی نمی‌داد و در بعضی ماه‌ها به وقت کافی پرداختی انجام نمی‌شد.')
QUOTE = 'حقوق ماهانه با تاخیر پرداخت می‌شد'


@override_settings(DEBUG=True)
class BulkCheckpointV222Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='v222-bulk-company', source_url='https://example.invalid/c/v222-bulk',
            source_name='synthetic', display_name='شرکت نمونهٔ تأیید گروهی',
            identity_status='verified', tech_status='verified', tehran_status='verified')
        cls.staff = get_user_model().objects.create_superuser(
            username='v222-reviewer', email='v222@example.invalid', password='test-only')
        cls.visitor = get_user_model().objects.create_user(
            username='v222-ordinary', password='test-only')
        cls.exps = []
        for i in range(2):
            cls.exps.append(PublicExperience.objects.create(
                company=cls.company, source_url=f'https://example.invalid/e/v222/{i}',
                source_kind='work', title='عنوان خصوصی آزمون', body=TEXT,
                content_sha256=str(i + 1) * 64,
                copyright_review='pending', company_attribution_status='unverified',
                independence_status='unknown'))
        for i, exp in enumerate(cls.exps):
            dims = {}
            for j, axis in enumerate(axes_for('work')):
                scored = i == 0 and j == 0
                dims[axis.key] = {
                    'score': 3 if scored else None,
                    'confidence': 93 if scored else 0,
                    'evidence': QUOTE if scored else '',
                    'explanation': ('تأخیر در پرداخت حقوق در تجربه بیان شده است' if scored
                                    else 'این متن در مورد معیار حاضر شاهد کافی ندارد'),
                }
            stage_one({
                'experience_id': exp.pk, 'company_id': cls.company.pk,
                'kind': 'work', 'source_content_sha256': exp.content_sha256,
                'story_sha256': story_digest(story_from_experience(exp)),
                'review_status': 'unverified_private_proposal',
                'model_name': 'GPT-6-synthetic',
                'prediction': {'detected_kind': 'work', 'kind_confidence': 91, 'dimensions': dims},
            })

    def setUp(self):
        self.url = reverse('dual-checkpoint-bulk-v222', args=[self.company.pk])

    def get_ready(self):
        self.client.force_login(self.staff)
        with patch.dict('os.environ', FLAGS):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response

    def approve_data(self, response):
        return {'snapshot': response.context['token'],
                'ready_count': str(response.context['ready_count']),
                'selected': [str(row['run'].pk) for row in response.context['rows']
                             if not row['reason']],
                'confirm_reviewed': 'yes', 'confirm_private': 'yes',
                'note': 'همه شواهد و محورهای این تجربه‌ها جداگانه بررسی و تطبیق داده شد.'}

    def approve(self, response):
        with patch.dict('os.environ', FLAGS):
            return self.client.post(self.url, self.approve_data(response))

    def test_private_preview_and_multi_company_approval(self):
        r = self.get_ready()
        self.assertEqual(r.context['ready_count'], 2)
        self.assertIn('no-store', r['Cache-Control'])
        self.assertContains(r, 'شرکت نمونهٔ تأیید گروهی')
        self.assertContains(r, 'بازبینی گروهی')
        response = self.approve(r)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 2)
        self.assertEqual(CheckpointApprovalReceipt.objects.count(), 1)
        self.assertEqual(CriteriaAnalysis.objects.filter(review_status='approved').count(), 1)
        self.assertEqual(CriteriaAnalysis.objects.filter(review_status='no_evaluable_scores').count(), 1)
        self.assertTrue(all(x == 3 for x in CriteriaAxisScore.objects.filter(
            semantic_status='approved').values_list('score', flat=True)))
        self.assertEqual(CriteriaAxisScore.objects.filter(semantic_status='abstained').count(), 11)
        self.assertTrue(checkpoint_release_ready(CriteriaAnalysis.objects.get(review_status='approved')))
        self.assertEqual(self.approve(r).status_code, 409)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 2)

    def test_reviewed_runs_remain_visible_and_reimport_is_idempotent(self):
        from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
        r = self.get_ready()
        self.assertEqual(self.approve(r).status_code, 302)
        with patch.dict('os.environ', FLAGS):
            dashboard = self.client.get(reverse('dual-checkpoint-company-v218', args=[self.company.pk]))
            self.assertEqual(dashboard.status_code, 200)
            self.assertEqual(dashboard.context['work']['pilot_valid_cases'], 2)
            for run in CriteriaAnalysis.objects.all():
                response = self.client.get(reverse('dual-checkpoint-detail-v218', args=[run.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'متن آماده‌شده')
        for exp in self.exps:
            run = CriteriaAnalysis.objects.get(experience=exp)
            dims = {}
            for axis in run.axis_scores.all():
                dims[axis.key] = {
                    'score': axis.score,
                    'confidence': axis.confidence,
                    'evidence': axis.evidence[0] if axis.evidence else '',
                    'explanation': axis.explanation,
                }
            original = {
                'experience_id': exp.pk, 'company_id': self.company.pk,
                'kind': 'work', 'source_content_sha256': exp.content_sha256,
                'story_sha256': story_digest(story_from_experience(exp)),
                'review_status': 'unverified_private_proposal',
                'model_name': 'GPT-6-synthetic',
                'prediction': {'detected_kind': 'work', 'kind_confidence': 91, 'dimensions': dims},
            }
            self.assertFalse(stage_one(original))
        self.assertEqual(CriteriaAnalysis.objects.count(), 2)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 2)

    def test_review_does_not_automatically_publish_scores(self):
        r = self.get_ready()
        self.assertEqual(self.approve(r).status_code, 302)
        with patch.dict('os.environ', {**FLAGS, 'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1',
                                       'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '1'}):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 0)
            public = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertNotContains(public, QUOTE)
        self.assertNotContains(public, TEXT)

    def test_rights_independence_attribution_review_and_dual_flags_required(self):
        r = self.get_ready()
        self.assertEqual(self.approve(r).status_code, 302)
        exp = self.exps[0]
        for field, decision in [('copyright', 'approved'), ('attribution', 'verified'),
                                ('independence', 'verified')]:
            ExperienceReviewEvent.objects.create(
                experience=exp, review_field=field, decision=decision,
                rationale='بررسی مستقل وضعیت منبع و استناد برای همین تصمیم',
                reviewer=self.staff, evidence_url='https://example.invalid/rights/evidence')
        CriteriaReviewEvent.objects.create(
            experience=exp, reviewer=self.staff, source_kind='work',
            criteria_version=version_for('work'), source_content_sha256=exp.content_sha256,
            decision='confirmed')
        self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 0)
        with patch.dict('os.environ', {'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '0'}):
            self.assertEqual(company_public_sufficiency(self.company)['work']['axes'][0]['dimension_experience_count'], 0)
        with patch.dict('os.environ', {'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '1'}):
            out = company_public_sufficiency(self.company)['work']['axes'][0]
            self.assertEqual(out['dimension_experience_count'], 1)
            self.assertEqual(out['score'], 3.0)
            self.assertEqual(company_public_sufficiency(self.company)['interview']['axes'][0]['dimension_experience_count'], 0)
            with patch.dict('os.environ', {'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1'}):
                public = self.client.get(reverse('company-detail', args=[self.company.pk]))
                self.assertContains(public, 'data-chart-mode="published"')
                self.assertNotContains(public, TEXT)

    def test_receipt_revoked_by_any_post_review_score_change(self):
        r = self.get_ready()
        self.assertEqual(self.approve(r).status_code, 302)
        run = CriteriaAnalysis.objects.get(review_status='approved')
        self.assertTrue(checkpoint_release_ready(run))
        CriteriaAxisScore.objects.filter(analysis=run, score=3).update(score=7)
        self.assertFalse(checkpoint_release_ready(CriteriaAnalysis.objects.get(pk=run.pk)))

    def test_select_subset_then_approve_remaining_later(self):
        response = self.get_ready()
        data = self.approve_data(response)
        first = data['selected'][0]
        data['selected'] = [first]
        with patch.dict('os.environ', FLAGS):
            result = self.client.post(self.url, data)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 1)
        self.assertEqual(CriteriaAnalysis.objects.filter(review_status='pilot_unverified').count(), 1)
        next_response = self.get_ready()
        self.assertEqual(next_response.context['ready_count'], 1)
        self.assertEqual(self.approve(next_response).status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 2)

    def test_reject_unknown_duplicate_or_empty_bulk_selection(self):
        response = self.get_ready()
        data = self.approve_data(response)
        examples = ([], ['9999999'], [data['selected'][0], data['selected'][0]])
        for selected in examples:
            with self.subTest(selected=selected):
                with patch.dict('os.environ', FLAGS):
                    actual = self.client.post(self.url, {**data, 'selected': selected})
                self.assertEqual(actual.status_code, 400)
                self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 0)

    def test_stale_snapshot_aborts_without_any_write(self):
        r = self.get_ready()
        CriteriaAxisScore.objects.filter(analysis__experience=self.exps[0], score=3).update(score=4)
        self.assertEqual(self.approve(r).status_code, 409)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 0)

    def test_unauthorized_and_incomplete_forms(self):
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.client.force_login(self.visitor)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {}).status_code, 403)
        r = self.get_ready()
        d = self.approve_data(r)
        d.pop('confirm_reviewed')
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.post(self.url, d).status_code, 400)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 0)

    def test_ineligible_blocked_experience_is_skipped_not_approved(self):
        PublicExperience.objects.filter(pk=self.exps[1].pk).update(copyright_review='blocked')
        r = self.get_ready()
        self.assertEqual(r.context['ready_count'], 1)
        self.assertEqual(self.approve(r).status_code, 302)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 1)
        self.assertEqual(CriteriaAnalysis.objects.filter(review_status='pilot_unverified').count(), 1)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                       ALLOWED_HOSTS=['private.example.invalid', 'testserver'])
    def test_staging_off_and_wrong_host_fail_closed(self):
        self.client.force_login(self.staff)
        flags = {'JOBIEW_CHECKPOINT_STAGING_ENABLED': '1',
                 'JOBIEW_CHECKPOINT_STAGING_HOST': 'private.example.invalid',
                 'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'www.example.invalid',
                 'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0'}
        with patch.dict('os.environ', flags):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='private.example.invalid').status_code, 404)
            self.assertEqual(self.client.get(self.url, secure=True, HTTP_HOST='testserver').status_code, 404)
            self.assertEqual(self.client.get(self.url, secure=True, HTTP_HOST='private.example.invalid').status_code, 200)


@override_settings(DEBUG=False, ALLOWED_HOSTS=['private.example.invalid'])
class CheckpointStagingGuardV222Tests(TestCase):
    def setUp(self):
        self.good = {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'jobiew_staging',
                     'HOST': '127.0.0.1'}
        self.flags = {'JOBIEW_CHECKPOINT_IMPORT_STAGING_ENABLED': '1',
                      'JOBIEW_CHECKPOINT_STAGING_ENABLED': '1',
                      'JOBIEW_CHECKPOINT_STAGING_HOST': 'private.example.invalid',
                      'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'www.example.invalid',
                      'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
                      'JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED': '0'}

    def guard(self, cfg=None, flags=None):
        with patch.dict('os.environ', flags or self.flags), patch(
                'criteria_v2.management.commands.stage_checkpoint_staging_v222.connection',
                SimpleNamespace(settings_dict=cfg or self.good)):
            return guard_dedicated_staging('jobiew_staging')

    def test_staging_guard_allows_only_separate_pinned_nonproduction_db(self):
        self.assertEqual(self.guard(), 'jobiew_staging')

    def test_staging_guard_rejects_production_names_remote_db_and_flags(self):
        for bad in ({**self.good, 'NAME': 'jobiew'},
                    {**self.good, 'NAME': 'jobiew_dev'},
                    {**self.good, 'HOST': 'prod-db.internal'},
                    {**self.good, 'ENGINE': 'django.db.backends.sqlite3'}):
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                self.guard(cfg=bad)
        for flag in ['JOBIEW_CHECKPOINT_IMPORT_STAGING_ENABLED',
                     'JOBIEW_CHECKPOINT_STAGING_ENABLED']:
            with self.subTest(flag=flag), self.assertRaises(CommandError):
                self.guard(flags={**self.flags, flag: '0'})
        with self.assertRaises(CommandError):
            self.guard(flags={**self.flags, 'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1'})

    @override_settings(ALLOWED_HOSTS=['.example.invalid'])
    def test_suffix_host_accepting_production_is_rejected(self):
        with self.assertRaises(CommandError):
            self.guard()