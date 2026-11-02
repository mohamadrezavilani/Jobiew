"""Run: python backend/manage.py test assessments.test_publication_simple_v105 --noinput"""
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS
from assessments.publication_simple_v105 import preliminary_blockers
from assessments.publication_workflow_v104 import public_company_assessments, publication_blockers
from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent


class SimplePublicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            username='v105admin', email='v105@example.org', password='test-password')
        cls.company = Company.objects.create(
            id='v105company', source_name='Test', source_url='https://example.org/company',
            display_name='شرکت نمونه', identity_status='verified', tech_status='verified')
        cls.exp = PublicExperience.objects.create(
            company=cls.company, source_url='https://example.org/experiences/v105',
            source_kind='work', title='یک نظر واقعی', body='متن نظر واقعی',
            content_sha256='a' * 64, copyright_review='approved')
        cls.ai = AiAssessment.objects.create(
            experience=cls.exp, model_name='local-test', prompt_version='five_v1',
            run_id='v105', criteria_version='five_v1', parse_status='imported_provisional')
        for i, (key, _) in enumerate(DIMENSIONS):
            if i == 4:
                AiDimension.objects.create(
                    assessment=cls.ai, key=key, score=None, confidence=0,
                    evidence=[], explanation='')
            else:
                AiDimension.objects.create(
                    assessment=cls.ai, key=key, score=5 + i, confidence=80,
                    evidence=['مشاهدهٔ مستقیم'], explanation='توضیح مبتنی بر شاهد')

    def setUp(self):
        self.client.force_login(self.staff)
        self.url = reverse('admin:assessments_aiassessment_publication_detail', args=[self.ai.pk])

    @staticmethod
    def _five_yes():
        return {'decision_' + key: 'yes' for key, _ in DIMENSIONS}

    def test_one_click_approval_creates_correct_abstention_and_publishes(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # The v107 button text is selected client-side after all five votes.
        self.assertContains(response, 'name="action" value="finish_review"')
        self.assertContains(response, "'تأیید و انتشار'")
        self.assertNotContains(response, 'verdict_')
        response = self.client.post(self.url, {'action': 'publish_reviewed', **self._five_yes()})
        self.assertEqual(response.status_code, 302)
        self.ai.refresh_from_db()
        self.exp.refresh_from_db()
        self.assertTrue(self.ai.publish_approved)
        self.assertEqual(self.exp.company_attribution_status, 'verified')
        self.assertEqual(self.exp.independence_status, 'verified')
        self.assertEqual(AiHumanReviewEvent.objects.filter(dimension__assessment=self.ai).count(), 5)
        null_dim = AiDimension.objects.get(assessment=self.ai, key=DIMENSIONS[-1][0])
        self.assertEqual(null_dim.human_review_events.first().verdict, 'correct_abstention')
        self.assertEqual(public_company_assessments(self.company)['approved_count'], 1)
        self.assertEqual(LogEntry.objects.filter(object_id=str(self.ai.pk),
            change_message__contains='PUBLISH_APPROVED').count(), 1)

    def test_pending_rights_no_longer_gates_derived_scores(self):
        self.exp.copyright_review = 'pending'
        self.exp.save(update_fields=['copyright_review'])
        self.client.post(self.url, {'action': 'finish_review', **self._five_yes()})
        self.ai.refresh_from_db(); self.exp.refresh_from_db()
        self.assertTrue(self.ai.publish_approved)
        self.assertEqual(self.exp.copyright_review, 'pending')
        self.assertFalse(ExperienceReviewEvent.objects.filter(review_field='copyright').exists())
        self.assertNotContains(self.client.get(reverse('company-detail', args=[self.company.pk])), self.exp.body)

    def test_company_not_verified_is_blocked(self):
        self.company.tech_status = 'unverified'
        self.company.save(update_fields=['tech_status'])
        self.client.post(self.url, {'action':'publish_reviewed', **self._five_yes()})
        self.ai.refresh_from_db()
        self.assertFalse(self.ai.publish_approved)
        self.assertEqual(AiHumanReviewEvent.objects.filter(dimension__assessment=self.ai).count(), 5)

    def test_prior_negative_verdict_kept_as_audited_history(self):
        first = AiDimension.objects.get(assessment=self.ai, key=DIMENSIONS[0][0])
        AiHumanReviewEvent.objects.create(dimension=first, reviewer=self.staff,
            verdict='unsupported', primary_error='wrong_dimension',
            note='شاهد به موضوع دیگری مربوط بوده است')
        self.assertTrue(publication_blockers(self.ai))
        self.client.post(self.url, {'action': 'publish_reviewed', **self._five_yes()})
        self.ai.refresh_from_db()
        self.assertTrue(self.ai.publish_approved)
        self.assertEqual(first.human_review_events.count(), 2)
        self.assertEqual(first.human_review_events.last().verdict, 'unsupported')

    def test_reject_is_atomic_and_public_safe(self):
        self.client.post(self.url, {'action': 'publish_reviewed', **self._five_yes()})
        self.client.post(self.url, {'action': 'quick_reject'})
        self.ai.refresh_from_db()
        self.assertFalse(self.ai.publish_approved)
        self.assertEqual(self.ai.independent_review_status, 'rejected')
        self.assertEqual(public_company_assessments(self.company)['approved_count'], 0)

    def test_no_permission_and_get_does_not_publish(self):
        self.client.get(self.url)
        self.ai.refresh_from_db()
        self.assertFalse(self.ai.publish_approved)
        person = get_user_model().objects.create_user(username='v105viewer', password='t', is_staff=True)
        self.client.force_login(person)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'action': 'publish_reviewed', **self._five_yes()}).status_code, 403)
        self.ai.refresh_from_db()
        self.assertFalse(self.ai.publish_approved)

    def test_archived_five_is_redirected_to_single_decision(self):
        legacy = reverse('admin:assessments_aiassessment_feasibility_review')
        r = self.client.get(legacy + '?assessment=' + str(self.ai.pk))
        self.assertEqual(r.status_code, 302)
        self.assertIn(self.url, r['Location'])
