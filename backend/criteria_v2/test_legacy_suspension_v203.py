"""Versioned stopgap acceptance tests: forbid old public scores, votes, paid Claude calls.

This suite remains after historical expectations were migrated, and must not be
silenced by re-enabling legacy endpoints. No network and no production writes.
"""
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension, DIMENSIONS
from assessments.publication_workflow_v104 import publication_blockers, public_company_assessments
from assessments.claude_validation_models_v111 import ClaudeValidationRun
from companies.models import Company
from experiences.models import PublicExperience
from voting.services import cast_vote, VoteDenied
from voting.models import ActiveVote, VoteRevision, IdentityVerification


class LegacyStopgapContractTests(TestCase):
    def setUp(self):
        self.staff=get_user_model().objects.create_superuser('dual203staff','dual203@example.test','test')
        self.company=Company.objects.create(id='dual203company',source_url='https://example.test/203',
            source_name='Test',display_name='شرکت ۲۰۳',identity_status='verified',tech_status='verified')
        self.work=PublicExperience.objects.create(company=self.company,source_kind='work',
            source_url='https://example.test/203/work', title='نظر کاری',body='متن اختصاصی و منتشرنشده',
            content_sha256='a'*64)
        self.interview=PublicExperience.objects.create(company=self.company,source_kind='interview',
            source_url='https://example.test/203/interview',title='نظر مصاحبه',body='متن اختصاصی و منتشرنشده مصاحبه',
            content_sha256='b'*64)
        self.assessment=AiAssessment.objects.create(experience=self.work,criteria_version='five_v1',
            model_name='historical',prompt_version='five_v1',run_id='dual203-history',
            publish_approved=True,independent_review_status='approved')
        for key, _ in DIMENSIONS:
            AiDimension.objects.create(assessment=self.assessment,key=key,score=8,
                confidence=90,evidence=['متن'],explanation='فقط تاریخی')

    def test_old_approval_flags_do_not_leak_to_public_and_do_not_change(self):
        self.assertTrue(publication_blockers(self.assessment))
        self.assertEqual(public_company_assessments(self.company)['approved_count'], 0)
        response=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertContains(response,'work6_v2')
        self.assertContains(response,'interview6_v2')
        self.assertNotContains(response,'متن اختصاصی و منتشرنشده')
        self.assertNotContains(response,'فقط تاریخی')
        self.assessment.refresh_from_db()
        self.assertTrue(self.assessment.publish_approved)  # preserved archival DB state

    def test_old_vote_cannot_create_revision_even_if_identity_verified(self):
        IdentityVerification.objects.create(user=self.staff,status='verified',provider='fixture')
        self.company.vote_enabled=True;self.company.save(update_fields=['vote_enabled'])
        with self.assertRaises(VoteDenied):
            cast_vote(user=self.staff,company_id=self.company.pk,scores={'work_conditions_pressure':8},
                      idempotency_key='dual203-legacy-001')
        self.assertFalse(VoteRevision.objects.exists())
        self.assertFalse(ActiveVote.objects.exists())

    @patch.dict('os.environ', {'ANTHROPIC_API_KEY':'test-not-real'})
    @patch('assessments.claude_validation_v111.call_claude')
    def test_old_claude_endpoint_rejects_without_paid_call(self, api):
        self.client.force_login(self.staff)
        response=self.client.post(reverse('admin:assessments_aiassessment_claude_run',
                                         args=[self.assessment.pk]), {'force':'true'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['error'],'legacy_scoring_suspended')
        api.assert_not_called()
        self.assertFalse(ClaudeValidationRun.objects.exists())
