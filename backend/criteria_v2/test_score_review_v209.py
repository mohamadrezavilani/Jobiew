"""Django integration acceptance: human six-axis adjudication must fail closed."""
import hashlib
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from companies.models import Company
from experiences.models import PublicExperience
from .engine_v207 import story_digest, story_from_experience
from .models import CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent, CriteriaScoreReviewEvent
from .registry import axes_for, version_for
from .sufficiency_v208 import company_public_sufficiency


class ScoreReviewWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='review-v209', source_url='https://example.test/company/review-v209',
            source_name='نمونه', display_name='شرکت بررسی شواهد',
            identity_status='verified', tech_status='verified')
        cls.staff = get_user_model().objects.create_superuser(
            'v209-review-staff', 'test@example.invalid', 'local-test-only')
        cls.other = get_user_model().objects.create_user(
            'v209-ordinary-user', password='local-test-only')
        body = ('حقوق ماهانه طبق قرارداد و همیشه به موقع پرداخت شد. '
                'مدیر با احترام و انصاف با کارکنان رفتار می‌کرد. '
                'در مورد سایر موضوعات تجربه‌ای ندارم.')
        cls.exp = PublicExperience.objects.create(
            company=cls.company, source_url='https://example.test/experience/review-v209',
            source_kind='work', title='شرایط همکاری', body=body,
            content_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(),
            copyright_review='approved', company_attribution_status='verified')
        cls.classification = CriteriaReviewEvent.objects.create(
            experience=cls.exp, reviewer=cls.staff,
            source_kind='work', criteria_version='work6_v2',
            source_content_sha256=cls.exp.content_sha256, decision='confirmed')
        story = story_from_experience(cls.exp)
        cls.analysis = CriteriaAnalysis.objects.create(
            experience=cls.exp, criteria_version='work6_v2',
            source_content_sha256=cls.exp.content_sha256,
            model_name='offline-test', prompt_version='jobiew_dual6_evidence_v207',
            run_id='test-score-review-v209', review_status='unreviewed',
            raw_payload={'engine':'jobiew_dual6_evidence_v207',
                         'story_sha256':story_digest(story)})
        axes = axes_for('work')
        for i, axis in enumerate(axes):
            score = 8 if i == 0 else None
            evidence = ['حقوق ماهانه طبق قرارداد و همیشه به موقع پرداخت شد'] if i == 0 else []
            CriteriaAxisScore.objects.create(
                analysis=cls.analysis, key=axis.key, score=score,
                confidence=95 if score is not None else 0,
                evidence=evidence, explanation='شاهد روشن از متن روایت ثبت‌شده موجود است' if score else
                'متن درباره این معیار شواهد معناداری ندارد')

    def url(self):
        return reverse('dual-score-review-detail', args=[self.analysis.pk])

    def post_data(self):
        return {'source_sha256': self.exp.content_sha256,
                'note': 'بررسی دستی شش محور و تأیید ارتباط شاهد با معیار انجام شد.',
                **{'axis_'+axis.key:('approve' if idx == 0 else 'abstain')
                   for idx, axis in enumerate(axes_for('work'))}}

    def test_anonymous_and_nonstaff_denied(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 403)

    def test_private_review_and_six_axes(self):
        self.client.force_login(self.staff)
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertIn('no-store', page['Cache-Control'])
        self.assertIn('noindex', page['X-Robots-Tag'])
        for axis in axes_for('work'):
            self.assertContains(page, axis.label)

    def test_partial_or_invalid_form_never_writes(self):
        self.client.force_login(self.staff)
        incomplete = self.post_data()
        incomplete.pop('axis_'+axes_for('work')[3].key)
        self.assertEqual(self.client.post(self.url(), incomplete).status_code, 400)
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.review_status, 'unreviewed')

    def test_success_has_immutable_audit_and_one_approved_dimension(self):
        self.client.force_login(self.staff)
        result = self.client.post(self.url(), self.post_data())
        self.assertEqual(result.status_code, 302)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.review_status, 'approved')
        events = list(CriteriaScoreReviewEvent.objects.all())
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0].decisions), 6)
        self.assertEqual(events[0].reviewer_id, self.staff.pk)
        with self.assertRaises(ValueError):
            events[0].delete()
        with self.assertRaises(ValueError):
            events[0].save()
        report = company_public_sufficiency(self.company)['work']
        self.assertEqual(report['axes'][0]['dimension_experience_count'], 1)
        self.assertEqual(report['axes'][0]['score'], 8.0)
        self.assertEqual(report['axes'][0]['data_sufficiency_status'], 'partial')
        self.assertEqual(report['axes'][1]['dimension_experience_count'], 0)
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 409)
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(), 1)

    def test_stale_content_blocks_approval(self):
        self.client.force_login(self.staff)
        PublicExperience.objects.filter(pk=self.exp.pk).update(content_sha256='f'*64)
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 409)
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())

    def test_later_exclusion_blocks_approval(self):
        self.client.force_login(self.staff)
        CriteriaReviewEvent.objects.create(
            experience=self.exp, reviewer=self.staff, source_kind='work',
            criteria_version='work6_v2', source_content_sha256=self.exp.content_sha256,
            decision='excluded', note='این روایت نباید برای محاسبه استفاده شود')
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 409)

    def test_bad_quote_blocks_approval(self):
        self.client.force_login(self.staff)
        CriteriaAxisScore.objects.filter(analysis=self.analysis, key=axes_for('work')[0].key).update(
            evidence=['جمله ساختگی که در متن روایت موجود نیست'])
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 409)

    def test_null_scores_cannot_be_approved_as_numbers(self):
        self.client.force_login(self.staff)
        data = self.post_data()
        data['axis_'+axes_for('work')[1].key] = 'approve'
        self.assertEqual(self.client.post(self.url(), data).status_code, 400)
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())

    def test_unknown_source_approval_blocks(self):
        self.client.force_login(self.staff)
        PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='pending')
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 409)
