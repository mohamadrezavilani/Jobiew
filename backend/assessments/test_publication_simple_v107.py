"""Regression tests for one-click publication of derived, non-verbatim AI scores."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS
from assessments.publication_workflow_v104 import public_company_assessments
from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent

class OneClickPublicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff=get_user_model().objects.create_superuser('v107admin','v107@example.org','pwd')
        cls.company=Company.objects.create(id='v107company',source_url='https://example.org/company',source_name='test',
            display_name='شرکت نمونه v107',identity_status='verified',tech_status='verified')
        cls.exp=PublicExperience.objects.create(company=cls.company,source_url='https://example.org/exp/107',
            source_kind='work',title='عنوان نظر',body='متن نظر خصوصی قابل مشاهده فقط توسط ادمین',
            content_sha256='f'*64,copyright_review='pending')
        cls.ai=AiAssessment.objects.create(experience=cls.exp,criteria_version='five_v1',
            model_name='test',prompt_version='v107',run_id='v107',parse_status='imported_provisional')
        for i,(key,_) in enumerate(DIMENSIONS):
            AiDimension.objects.create(assessment=cls.ai,key=key,score=7 if i<2 else None,
                confidence=75 if i<2 else 0,evidence=['شاهد'] if i<2 else [],
                explanation='توضیح' if i<2 else '')
    def setUp(self):
        self.client.force_login(self.staff)
        self.url=reverse('admin:assessments_aiassessment_publication_detail',args=[self.ai.pk])
    def votes(self,negative=()):
        return {'decision_'+key:'no' if key in negative else 'yes' for key,_ in DIMENSIONS}
    def test_one_form_one_click_pending_rights_publishes_no_raw_text(self):
        html=self.client.get(self.url).content.decode()
        # Each dimension is a binary choice: two radio inputs, one logical decision.
        self.assertEqual(html.count('type="radio" name="decision_'), 10)
        for key, _ in DIMENSIONS:
            self.assertEqual(html.count(f'name="decision_{key}"'), 2)
        self.assertEqual(html.count('value="yes"'), 5)
        self.assertEqual(html.count('value="no"'), 5)
        self.assertIn('name="action" value="finish_review"',html)
        self.assertNotIn('value="review_dimensions"',html)
        self.assertNotIn('مدیریت بررسی مجوز منبع',html)
        self.assertNotIn('نشانی سند مجوز',html)
        self.assertNotIn('data-publish-ready',html)
        response=self.client.post(self.url,{'action':'finish_review',**self.votes()})
        self.assertEqual(response.status_code,302)
        self.ai.refresh_from_db();self.exp.refresh_from_db()
        self.assertTrue(self.ai.publish_approved)
        self.assertEqual(self.exp.copyright_review,'pending')
        self.assertEqual(AiHumanReviewEvent.objects.filter(dimension__assessment=self.ai).count(),5)
        self.assertFalse(ExperienceReviewEvent.objects.filter(review_field='copyright').exists())
        self.assertEqual(public_company_assessments(self.company)['approved_count'],1)
        public=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertNotContains(public,self.exp.body)
    def test_explicit_block_still_prevents_publishing(self):
        self.exp.copyright_review='blocked';self.exp.save(update_fields=['copyright_review'])
        self.client.post(self.url,{'action':'finish_review',**self.votes()})
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
        self.assertEqual(public_company_assessments(self.company)['approved_count'],0)
    def test_one_negative_records_and_stays_unpublished(self):
        self.client.post(self.url,{'action':'finish_review',**self.votes({DIMENSIONS[2][0]})})
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
        self.assertEqual(AiHumanReviewEvent.objects.filter(dimension__assessment=self.ai).count(),5)
        self.client.post(self.url,{'action':'finish_review',**self.votes()})
        self.ai.refresh_from_db();self.assertTrue(self.ai.publish_approved)
        self.client.post(self.url,{'action':'finish_review',**self.votes({DIMENSIONS[0][0]})})
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
        self.assertEqual(public_company_assessments(self.company)['approved_count'],0)
    def test_incomplete_five_not_accepted(self):
        incomplete=self.votes();del incomplete['decision_'+DIMENSIONS[0][0]]
        self.client.post(self.url,{'action':'finish_review',**incomplete})
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
        self.assertEqual(AiHumanReviewEvent.objects.filter(dimension__assessment=self.ai).count(),0)
    def test_no_access_via_non_staff(self):
        user=get_user_model().objects.create_user('v107plain','v107plain@example.org','pwd')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code,302) # admin login redirect
        response=self.client.post(self.url,{'action':'finish_review',**self.votes()})
        self.assertIn(response.status_code,(302,403))
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
