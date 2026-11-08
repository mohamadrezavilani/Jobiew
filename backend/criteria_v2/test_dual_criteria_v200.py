"""Structure, validation, and safety invariants. Run with Django test runner."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from companies.models import Company
from experiences.models import PublicExperience
from .models import CriteriaReviewEvent, CriteriaAnalysis, CriteriaAxisScore
from .registry import AXES, VERSIONS, axes_for, public_axes, validate_scoring_payload


class RegistryTests(TestCase):
    def test_exactly_six_independent_axes(self):
        self.assertEqual({k: len(axes_for(k)) for k in VERSIONS}, {'work': 6, 'interview': 6})
        self.assertFalse(set(x.key for x in AXES['work']) & set(x.key for x in AXES['interview']))
        self.assertEqual({k: {x['score'] for x in v} for k, v in public_axes().items()},
                         {'work': {None}, 'interview': {None}})

    def test_no_legacy_or_wrong_type_scoring(self):
        dim = {x.key: {'score': None, 'evidence': ''} for x in AXES['work']}
        valid = dict(criteria_version='work6_v2', source_kind='work',
                     source_content_sha256='a'*64, dimensions=dim)
        self.assertEqual(len(validate_scoring_payload(valid, source_kind='work', source_sha256='a'*64)), 6)
        with self.assertRaises(ValueError):
            validate_scoring_payload(valid, source_kind='interview', source_sha256='a'*64)
        with self.assertRaises(ValueError):
            validate_scoring_payload(dict(valid, criteria_version='five_v1'), source_kind='work', source_sha256='a'*64)
        dim2 = dict(dim, work_management_culture={'score': 0, 'evidence': 'x'})
        with self.assertRaises(ValueError):
            validate_scoring_payload(dict(valid, dimensions=dim2), source_kind='work', source_sha256='a'*64)


class ReviewSeparationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='dual-review-test', password='local-test-only')
        self.company = Company.objects.create(
            id='dual_v200_company', source_url='https://example.test/companies/d',
            source_name='نمونه', display_name='شرکت نمونه')
        self.work = PublicExperience.objects.create(
            company=self.company, source_url='https://example.test/experiences/work1',
            source_kind='work', title='تجربه محیط کار', body='روایت شرایط کاری', content_sha256='a'*64)
        self.interview = PublicExperience.objects.create(
            company=self.company, source_url='https://example.test/experiences/interview1',
            source_kind='interview', title='تجربه مصاحبه', body='روایت مصاحبه', content_sha256='b'*64)

    def test_all_old_comments_are_pending_without_mutation(self):
        from .views import pending_queryset
        self.assertEqual(CriteriaReviewEvent.objects.count(), 0)
        self.assertEqual(pending_queryset('work').count(), 1)
        self.assertEqual(pending_queryset('interview').count(), 1)
        self.assertEqual(CriteriaAnalysis.objects.count(), 0)
        self.assertEqual(CriteriaAxisScore.objects.count(), 0)

    def test_work_confirmation_does_not_clear_interview_queue(self):
        from .views import pending_queryset
        event = CriteriaReviewEvent.objects.create(
            experience=self.work, reviewer=self.user, source_kind='work',
            criteria_version='work6_v2', source_content_sha256='a'*64, decision='confirmed')
        self.assertEqual(pending_queryset('work').count(), 0)
        self.assertEqual(pending_queryset('interview').count(), 1)
        with self.assertRaises(ValueError):
            event.delete()
        with self.assertRaises(ValueError):
            event.save()
        PublicExperience.objects.filter(pk=self.work.pk).update(content_sha256='c'*64)
        self.assertEqual(pending_queryset('work').count(), 1)

    def test_reject_cross_scope_review_and_scores(self):
        with self.assertRaises(ValidationError):
            CriteriaReviewEvent.objects.create(
                experience=self.work, reviewer=self.user, source_kind='interview',
                criteria_version='interview6_v2', source_content_sha256='a'*64,
                decision='confirmed')
        run = CriteriaAnalysis.objects.create(
            experience=self.work, criteria_version='work6_v2',
            source_content_sha256='a'*64, model_name='offline',
            prompt_version='placeholder', run_id='dual-test-run-1')
        with self.assertRaises(ValidationError):
            CriteriaAxisScore.objects.create(analysis=run,
                key='interview_quality_fairness', score=5, evidence=['example'], confidence=40)
        self.assertEqual(CriteriaAxisScore.objects.count(), 0)
