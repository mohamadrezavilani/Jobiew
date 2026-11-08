"""MVP 1.0 sufficiency acceptance against real Django models (disposable test DB)."""
import hashlib
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from companies.models import Company
from experiences.models import PublicExperience
from .models import CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent
from .engine_v207 import story_from_experience, story_digest
from .registry import axes_for, version_for
from .sufficiency_v208 import company_public_sufficiency, configured_threshold


class DataSufficiencyIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='sufficiency-v208', source_url='https://example.test/company/sufficiency',
            source_name='نمونه', display_name='شرکت کفایت داده',
            identity_status='verified', tech_status='verified')
        cls.reviewer = get_user_model().objects.create_user(
            username='sufficiency-staff', password='local-only')

    def add_experience(self, kind='work', *, verified=True, copyright_ok=True, duplicate=False):
        self.counter = getattr(self, 'counter', 0) + 1
        body = ('حقوق هر ماه بدون تأخیر و به صورت منظم پرداخت می‌شد و قرارداد روشن بود. '
                'مدیر با احترام و انصاف با کارکنان برخورد می‌کرد.' if kind == 'work' else
                'مصاحبه‌کننده مؤدب بود و به همه سؤال‌ها با احترام پاسخ می‌داد. '
                'نتیجه مصاحبه در موعد اعلام‌شده ارسال شد.')
        return PublicExperience.objects.create(
            company=self.company,
            source_url=f'https://example.test/exp/sufficiency/{kind}/{self.counter}',
            source_kind=kind, body=body, title='روایت نمونه',
            content_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(),
            copyright_review='approved' if copyright_ok else 'pending',
            company_attribution_status='verified' if verified else 'unverified',
            independence_status='duplicate' if duplicate else 'unknown')

    def add_analysis(self, exp, axes=(0,), *, approved=True, semantic_approved=True,
                     score=7, confirmed=True, evidence_valid=True):
        if confirmed:
            CriteriaReviewEvent.objects.create(
                experience=exp, reviewer=self.reviewer, source_kind=exp.source_kind,
                criteria_version=version_for(exp.source_kind),
                source_content_sha256=exp.content_sha256, decision='confirmed')
        story=story_from_experience(exp)
        run = CriteriaAnalysis.objects.create(
            experience=exp, criteria_version=version_for(exp.source_kind),
            source_content_sha256=exp.content_sha256,
            model_name='offline-reviewed-example', prompt_version='jobiew_dual6_evidence_v207',
            run_id=f'test-suff-v208-{exp.pk}-{CriteriaAnalysis.objects.count()}',
            review_status='approved' if approved else 'unreviewed',
            raw_payload={'engine': 'jobiew_dual6_evidence_v207',
                         'story_sha256': story_digest(story)})
        for idx in axes:
            fragment = ('حقوق هر ماه بدون تأخیر' if exp.source_kind == 'work' else
                        'مصاحبه‌کننده مؤدب بود')
            if not evidence_valid:
                fragment = 'جمله ساختگی بدون وجود در متن منبع'
            CriteriaAxisScore.objects.create(
                analysis=run, key=axes_for(exp.source_kind)[idx].key,
                score=score, confidence=95, evidence=[fragment],
                explanation='توضیح انسانی روشن بر اساس روایت',
                semantic_status='approved' if semantic_approved else 'unreviewed')
        return run

    def result(self, kind='work', idx=0):
        return company_public_sufficiency(self.company)[kind]['axes'][idx]

    def test_no_scores_without_any_approved_experiences(self):
        exp=self.add_experience(); self.add_analysis(exp, approved=False)
        self.assertEqual(self.result()['dimension_experience_count'],0)
        self.assertIsNone(self.result()['score'])

    def test_single_related_experience_is_partial_and_scored(self):
        exp=self.add_experience(); self.add_analysis(exp)
        self.assertEqual(self.result()['dimension_experience_count'],1)
        self.assertEqual(self.result()['data_sufficiency_status'],'partial')
        self.assertEqual(self.result()['score'],7.0)

    def test_five_partial_six_sufficient(self):
        for _ in range(5):self.add_analysis(self.add_experience())
        self.assertEqual(self.result()['data_sufficiency_status'],'partial')
        self.add_analysis(self.add_experience())
        self.assertEqual(self.result()['data_sufficiency_status'],'sufficient')
        self.assertEqual(self.result()['dimension_experience_count'],6)

    def test_one_experience_can_count_for_two_axes(self):
        self.add_analysis(self.add_experience(), axes=(0,2))
        out=company_public_sufficiency(self.company)['work']
        self.assertEqual(out['total_experiences'],1)
        self.assertEqual(sum(x['dimension_experience_count'] for x in out['axes']),2)

    def test_double_approved_analysis_for_one_experience_counts_once(self):
        exp=self.add_experience(); self.add_analysis(exp)
        self.add_analysis(exp, confirmed=False, score=9)
        self.assertEqual(self.result()['dimension_experience_count'],1)
        self.assertEqual(self.result()['score'],9.0)  # most recent approved run

    def test_work_interview_never_mix(self):
        self.add_analysis(self.add_experience('work'))
        self.add_analysis(self.add_experience('interview'))
        out=company_public_sufficiency(self.company)
        self.assertEqual(out['work']['axes'][0]['dimension_experience_count'],1)
        self.assertEqual(out['interview']['axes'][0]['dimension_experience_count'],1)
        self.assertEqual(out['work']['total_experiences'],1)
        self.assertEqual(out['interview']['total_experiences'],1)

    def test_not_valid_not_reviewed_excluded(self):
        self.add_analysis(self.add_experience(verified=False))
        self.add_analysis(self.add_experience(copyright_ok=False))
        self.add_analysis(self.add_experience(duplicate=True))
        self.add_analysis(self.add_experience(), confirmed=False)
        self.add_analysis(self.add_experience(), evidence_valid=False)
        self.add_analysis(self.add_experience(), semantic_approved=False)
        self.assertEqual(self.result()['dimension_experience_count'],0)

    def test_exclusion_review_after_confirmation_removes_score(self):
        exp=self.add_experience(); self.add_analysis(exp)
        self.assertEqual(self.result()['dimension_experience_count'],1)
        CriteriaReviewEvent.objects.create(
            experience=exp, reviewer=self.reviewer, source_kind='work',
            criteria_version='work6_v2', source_content_sha256=exp.content_sha256,
            decision='excluded', note='این تجربه نباید استفاده شود')
        self.assertEqual(self.result()['dimension_experience_count'],0)

    def test_changed_source_digest_invalidates_previous_analysis(self):
        exp=self.add_experience(); self.add_analysis(exp)
        PublicExperience.objects.filter(pk=exp.pk).update(content_sha256='f'*64)
        self.assertEqual(self.result()['dimension_experience_count'],0)

    def test_unverified_company_does_not_publish_scores(self):
        self.add_analysis(self.add_experience())
        self.company.identity_status = 'unverified'; self.company.save(update_fields=['identity_status'])
        self.assertEqual(self.result()['dimension_experience_count'],0)

    def test_public_flag_off_remains_empty(self):
        self.add_analysis(self.add_experience())
        with patch.dict('os.environ', {'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0'}):
            response=self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-chart-mode="empty"',count=2)
        self.assertNotContains(response, 'data-chart-mode="published"')

    def test_public_flag_on_shows_partial_score_and_count(self):
        self.add_analysis(self.add_experience())
        with patch.dict('os.environ', {'JOBIEW_DUAL6_PUBLICATION_ENABLED': '1'}):
            response=self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-chart-mode="published"')
        self.assertContains(response,'اطلاعات ناقص')
        self.assertContains(response,'تجربهٔ مرتبط و قابل‌ارزیابی')
        self.assertNotContains(response,'۶+۶ از نسخه قبلی')

    def test_configurable_threshold(self):
        with patch.dict('os.environ', {'JOBIEW_MIN_SUFFICIENT_EXPERIENCES': '3'}):
            self.assertEqual(configured_threshold(),3)
        with patch.dict('os.environ', {'JOBIEW_MIN_SUFFICIENT_EXPERIENCES': 'garbage'}):
            with self.assertRaises(ValueError): configured_threshold()

