"""Disposable Django DB tests. No private source files or AI requests."""
import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from companies.models import Company
from experiences.models import PublicExperience
from .checkpoint_contract_v218 import ENGINE, STATUS, CheckpointError
from .engine_v207 import story_digest, story_from_experience
from .management.commands.stage_dual6_checkpoint_v218 import stage_one, check_candidate
from .models import CriteriaAnalysis, CriteriaAxisScore, CriteriaScoreReviewEvent
from .registry import axes_for

FLAGS = {'JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED': '1',
         'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0'}
STORY = ('حقوق هر ماه دو ماه با تأخیر پرداخت می‌شد و مدیر شرکت درباره علت '
         'تاخیر توضیح مشخصی نمی‌داد، ولی همکاران رفتار محترمانه داشتند.')
QUOTE = 'حقوق هر ماه دو ماه با تأخیر پرداخت می‌شد'


@override_settings(DEBUG=True)
class CheckpointV218DBTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(id='v218-company',
            source_url='https://example.invalid/company', source_name='نمونه',
            display_name='شرکت آزمایشی خصوصی')
        cls.user = get_user_model().objects.create_superuser(
            username='v218-staff', email='v218@example.invalid', password='test-only')
        cls.other = get_user_model().objects.create_user(username='v218-other', password='test-only')
        cls.exp = PublicExperience.objects.create(company=cls.company,
            source_url='https://example.invalid/story', source_kind='work',
            title='نمونه', body=STORY, content_sha256='a'*64,
            copyright_review='pending', company_attribution_status='unverified')

    def proposal(self):
        story = story_from_experience(self.exp)
        dims = {}
        for idx, axis in enumerate(axes_for('work')):
            dims[axis.key] = ({'score': 2, 'confidence': 80, 'evidence': QUOTE,
                 'explanation': 'تاخیر در پرداخت حقوق به‌صورت صریح گزارش شده است'}
                if idx == 0 else
                {'score': None, 'confidence': 0, 'evidence': '',
                 'explanation': 'در متن شواهد کافی برای ارزیابی این معیار نیست'})
        return {
            'experience_id': self.exp.pk, 'company_id': self.company.pk,
            'kind': 'work', 'source_content_sha256': self.exp.content_sha256,
            'story_sha256': story_digest(story),
            'review_status': 'unverified_private_proposal',
            'model_name': 'GPT-6-conversation-manual-review',
            'prediction': {'detected_kind': 'work', 'kind_confidence': 85, 'dimensions': dims}}

    def test_staging_is_idempotent_and_unapproved(self):
        self.assertTrue(stage_one(self.proposal()))
        self.assertFalse(stage_one(self.proposal()))
        self.assertEqual(CriteriaAnalysis.objects.count(), 1)
        self.assertEqual(CriteriaAxisScore.objects.count(), 6)
        run = CriteriaAnalysis.objects.get()
        self.assertEqual(run.review_status, STATUS)
        self.assertEqual(run.raw_payload['engine'], ENGINE)
        self.assertNotIn(STORY, str(run.raw_payload))
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 0)
        self.assertFalse(CriteriaAxisScore.objects.filter(semantic_status='approved').exists())

    def test_prior_pilot_is_not_mutated(self):
        old = CriteriaAnalysis.objects.create(experience=self.exp,
            criteria_version='work6_v2', source_content_sha256=self.exp.content_sha256,
            model_name='old', prompt_version='old', run_id='old-v218',
            review_status='pilot_unverified', raw_payload={'engine':'jobiew_private_assistant_pilot_v212'})
        stage_one(self.proposal())
        old.refresh_from_db()
        self.assertEqual(old.review_status,'pilot_unverified')
        self.assertEqual(old.raw_payload['engine'],'jobiew_private_assistant_pilot_v212')
        self.assertEqual(CriteriaAnalysis.objects.count(),2)

    def test_changed_source_not_accepted(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(content_sha256='b'*64)
        with self.assertRaises(CheckpointError):
            stage_one(self.proposal())
        self.assertFalse(CriteriaAnalysis.objects.exists())

    def test_changed_proposal_conflict_refused(self):
        p = self.proposal()
        stage_one(p)
        p['prediction']['dimensions']['work_compensation_fairness']['score'] = 3
        with self.assertRaises(CheckpointError):
            stage_one(p)
        self.assertEqual(CriteriaAnalysis.objects.count(),1)

    def test_existing_run_with_modified_score_is_not_silently_accepted(self):
        stage_one(self.proposal())
        run = CriteriaAnalysis.objects.get()
        CriteriaAxisScore.objects.filter(analysis=run, key='work_compensation_fairness').update(score=10)
        with self.assertRaisesRegex(CheckpointError, 'STAGED_RUN_CHANGED'):
            stage_one(self.proposal())
        self.assertEqual(CriteriaAnalysis.objects.count(), 1)

    def test_blocked_source_not_accepted(self):
        PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='blocked')
        with self.assertRaises(CheckpointError):
            stage_one(self.proposal())
        self.assertFalse(CriteriaAnalysis.objects.exists())

    def test_authorization_and_public_isolation(self):
        stage_one(self.proposal())
        url = reverse('dual-checkpoint-dashboard-v218')
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(url).status_code,403)
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(url).status_code,403)
            self.client.force_login(self.user)
            r = self.client.get(url)
            self.assertEqual(r.status_code,200)
            self.assertIn('no-store',r['Cache-Control'])
            self.assertContains(r,'تأییدنشده')
            company = self.client.get(reverse('dual-checkpoint-company-v218', args=[self.company.pk]))
            self.assertEqual(company.context['work']['axes'][0]['score'],2)
            self.assertIsNone(company.context['work']['axes'][1]['score'])
            self.assertNotContains(company,STORY)
            self.assertNotContains(company,QUOTE)
            public = self.client.get(reverse('company-detail',args=[self.company.pk]))
            self.assertNotContains(public,QUOTE)

    @override_settings(DEBUG=False)
    def test_hidden_in_production(self):
        stage_one(self.proposal())
        self.client.force_login(self.user)
        with patch.dict('os.environ',FLAGS):
            self.assertEqual(self.client.get(reverse('dual-checkpoint-dashboard-v218')).status_code,404)

    def test_publication_flag_closes_private_view(self):
        stage_one(self.proposal())
        self.client.force_login(self.user)
        with patch.dict('os.environ',{**FLAGS,'JOBIEW_DUAL6_PUBLICATION_ENABLED':'1'}):
            self.assertEqual(self.client.get(reverse('dual-checkpoint-dashboard-v218')).status_code,404)

    def test_no_post_and_no_review_approval(self):
        stage_one(self.proposal())
        self.client.force_login(self.user)
        with patch.dict('os.environ',FLAGS):
            self.assertEqual(self.client.post(reverse('dual-checkpoint-dashboard-v218')).status_code,405)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(),0)


@override_settings(DEBUG=False, ALLOWED_HOSTS=['private-staging.example.invalid', 'testserver'])
class CheckpointV218StagingAccessTests(TestCase):
    """Confirm that staging is not accidentally a DEBUG-only route or public."""
    setUpTestData = classmethod(CheckpointV218DBTests.setUpTestData.__func__)
    def test_disabled_by_default(self):
        self.client.force_login(self.user)
        with patch.dict('os.environ', {'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
                                        'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0'}):
            self.assertEqual(self.client.get(reverse('dual-checkpoint-dashboard-v218'),
                             secure=True, HTTP_HOST='private-staging.example.invalid').status_code, 404)

    def test_requires_https_exact_host_and_staff(self):
        url = reverse('dual-checkpoint-dashboard-v218')
        flags = {'JOBIEW_CHECKPOINT_STAGING_ENABLED': '1',
                 'JOBIEW_CHECKPOINT_STAGING_HOST': 'private-staging.example.invalid',
                 'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0'}
        with patch.dict('os.environ', flags):
            self.client.force_login(self.user)
            self.assertEqual(self.client.get(url, HTTP_HOST='private-staging.example.invalid').status_code, 404)
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST='testserver').status_code, 404)
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST='private-staging.example.invalid').status_code, 200)
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST='private-staging.example.invalid').status_code, 403)

    def test_publication_flag_closes_staging(self):
        self.client.force_login(self.user)
        with patch.dict('os.environ', {'JOBIEW_CHECKPOINT_STAGING_ENABLED': '1',
                   'JOBIEW_CHECKPOINT_STAGING_HOST': 'private-staging.example.invalid',
                   'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1'}):
            self.assertEqual(self.client.get(reverse('dual-checkpoint-dashboard-v218'),
                            secure=True, HTTP_HOST='private-staging.example.invalid').status_code, 404)


class CheckpointV218PostgresConcurrencyTests(TransactionTestCase):
    """Real row-lock race check; executes only against ephemeral PostgreSQL CI.

    Uses no user-provided data. TransactionTestCase is essential here: TestCase
    transaction wrappers would mask concurrent workers' writes.
    """

    def setUp(self):
        self.company = Company.objects.create(
            id='v218-race-company', source_url='https://example.invalid/race-company',
            source_name='ساختگی', display_name='آزمایش هم‌زمانی خصوصی')
        self.exp = PublicExperience.objects.create(
            company=self.company, source_url='https://example.invalid/race-story',
            source_kind='work', title='ساختگی', body=STORY, content_sha256='c' * 64,
            copyright_review='pending', company_attribution_status='unverified')

    def test_two_concurrent_imports_have_one_immutable_run(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connection

        if connection.vendor != 'postgresql':
            self.skipTest('Real row locking is a PostgreSQL-only assertion')
        row = CheckpointV218DBTests.proposal(self)
        barrier = Barrier(2)

        def worker(_):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return stage_one(row)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(worker, (1, 2)))

        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(CriteriaAnalysis.objects.count(), 1)
        self.assertEqual(CriteriaAxisScore.objects.count(), 6)
        self.assertEqual(CriteriaAnalysis.objects.get().review_status, STATUS)
