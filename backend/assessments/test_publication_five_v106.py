"""Run: python backend/manage.py test assessments.test_publication_five_v106 --noinput"""
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS
from assessments.publication_workflow_v104 import public_company_assessments
from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent


class FiveDecisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser('v106admin','v106@example.org','pass')
        cls.company = Company.objects.create(id='v106company', source_url='https://example.org/co',
            source_name='test', display_name='نمونه', identity_status='verified',tech_status='verified')
        cls.experience = PublicExperience.objects.create(company=cls.company,
            source_url='https://example.org/exp/1', source_kind='work', title='یک تجربه',
            body='متن کامل تجربه درباره شرکت و شرایط کاری', content_sha256='e'*64,
            copyright_review='approved')
        cls.assessment = AiAssessment.objects.create(experience=cls.experience,
            criteria_version='five_v1', model_name='test-model', prompt_version='v106',
            run_id='v106', parse_status='imported_provisional')
        for idx,(key,_) in enumerate(DIMENSIONS):
            AiDimension.objects.create(assessment=cls.assessment,key=key,
                score=(None if idx==4 else 5+idx), confidence=(0 if idx==4 else 70),
                evidence=([] if idx in (1,3,4) else ['شاهد ثبت شده']),
                explanation=('' if idx in (1,3,4) else 'توضیح معتبر'))

    def setUp(self):
        self.client.force_login(self.staff)
        self.url = reverse('admin:assessments_aiassessment_publication_detail', args=[self.assessment.pk])

    def votes(self, negative=()):
        return {'decision_'+key: 'no' if key in negative else 'yes' for key,_ in DIMENSIONS}

    def test_form_shows_five_binary_decisions_and_no_license_input(self):
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        content=response.content.decode()
        for key,_ in DIMENSIONS:
            self.assertIn('name="decision_'+key+'"',content)
        self.assertNotIn('name="rights_evidence_url"',content)
        # v107 uses one finish_review submit; JS chooses its title after the
        # reviewer selects five decisions (publish or record rejection).
        self.assertIn('name="action" value="finish_review"', content)
        self.assertIn("'تأیید و انتشار'", content)
        self.assertIn("'ثبت عدم تأیید'", content)
        self.assertEqual(content.count('value="yes"'),5)
        self.assertEqual(content.count('value="no"'),5)

    def test_manual_acceptance_without_extracted_machine_quote(self):
        response=self.client.post(self.url, {'action':'publish_reviewed', **self.votes()})
        self.assertEqual(response.status_code,302)
        self.assessment.refresh_from_db();self.experience.refresh_from_db()
        self.assertTrue(self.assessment.publish_approved)
        self.assertEqual(AiHumanReviewEvent.objects.filter(
            dimension__assessment=self.assessment).count(),5)
        null_dimension=AiDimension.objects.get(assessment=self.assessment,key=DIMENSIONS[-1][0])
        self.assertEqual(null_dimension.human_review_events.first().verdict,'correct_abstention')
        self.assertEqual(public_company_assessments(self.company)['approved_count'],1)
        self.assertEqual(LogEntry.objects.filter(object_id=str(self.assessment.pk),
            change_message__contains='PUBLISH_APPROVED').count(),1)

    def test_missing_one_vote_does_not_save_anything(self):
        v=self.votes();del v['decision_'+DIMENSIONS[0][0]]
        self.client.post(self.url, {'action':'publish_reviewed', **v})
        self.assessment.refresh_from_db()
        self.assertFalse(self.assessment.publish_approved)
        self.assertFalse(AiHumanReviewEvent.objects.exists())

    def test_rejection_saves_without_requiring_explanation_and_blocks_publication(self):
        r=self.client.post(self.url, {'action':'review_dimensions',**self.votes([DIMENSIONS[2][0]])})
        self.assertEqual(r.status_code,302)
        dim=AiDimension.objects.get(assessment=self.assessment,key=DIMENSIONS[2][0])
        self.assertEqual(dim.human_review_events.first().verdict,'uncertain')
        self.client.post(self.url, {'action':'publish_reviewed',**self.votes([DIMENSIONS[2][0]])})
        self.assessment.refresh_from_db()
        self.assertFalse(self.assessment.publish_approved)
        self.client.post(self.url, {'action':'publish_reviewed',**self.votes()})
        self.assessment.refresh_from_db()
        self.assertTrue(self.assessment.publish_approved)
        self.assertEqual(dim.human_review_events.count(),2)

    def test_negative_later_revokes_public_visibility(self):
        self.client.post(self.url, {'action':'publish_reviewed',**self.votes()})
        self.client.post(self.url, {'action':'review_dimensions',**self.votes([DIMENSIONS[0][0]])})
        self.assessment.refresh_from_db()
        self.assertFalse(self.assessment.publish_approved)
        self.assertEqual(public_company_assessments(self.company)['approved_count'],0)

    def test_copyright_pending_does_not_block_derived_scores(self):
        self.experience.copyright_review='pending'
        self.experience.save(update_fields=['copyright_review'])
        self.client.post(self.url, {'action':'finish_review',**self.votes()})
        self.assessment.refresh_from_db()
        self.experience.refresh_from_db()
        self.assertTrue(self.assessment.publish_approved)
        self.assertEqual(self.experience.copyright_review,'pending')
        self.assertFalse(ExperienceReviewEvent.objects.filter(review_field='copyright').exists())
        self.assertEqual(AiHumanReviewEvent.objects.filter(dimension__assessment=self.assessment).count(),5)

    def test_prevent_unverified_company_and_missing_source_text(self):
        self.company.identity_status='unverified';self.company.save(update_fields=['identity_status'])
        self.client.post(self.url, {'action':'publish_reviewed',**self.votes()})
        self.assessment.refresh_from_db();self.assertFalse(self.assessment.publish_approved)
        self.company.identity_status='verified';self.company.save(update_fields=['identity_status'])
        self.experience.body='';self.experience.save(update_fields=['body'])
        self.client.post(self.url, {'action':'publish_reviewed',**self.votes()})
        self.assessment.refresh_from_db();self.assertFalse(self.assessment.publish_approved)

    def test_legacy_quick_publish_without_votes_does_not_bypass_review(self):
        self.client.post(self.url, {'action':'quick_publish'})
        self.assessment.refresh_from_db()
        self.assertFalse(self.assessment.publish_approved)
        self.assertFalse(AiHumanReviewEvent.objects.exists())

    def test_unauthorized_user_cannot_view_or_publish(self):
        staff=get_user_model().objects.create_user('v106viewer',password='pass',is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.assertEqual(self.client.post(self.url, {'action':'publish_reviewed',**self.votes()}).status_code,403)
