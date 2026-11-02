"""Security and publication tests; no external services."""
from django.contrib.auth import get_user_model
from django.contrib.admin.models import LogEntry
from django.test import TestCase
from django.urls import reverse

from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS
from assessments.publication_workflow_v104 import publication_blockers, public_company_assessments, set_publication
from companies.models import Company
from experiences.models import PublicExperience


class PublicationV104Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(username='v104admin',email='test@example.org',password='test')
        cls.company = Company.objects.create(id='v104',source_url='https://example.org/co',source_name='آزمایشی',
                                             display_name='شرکت آزمایش',identity_status='verified',tech_status='verified')
        cls.exp = PublicExperience.objects.create(company=cls.company,source_url='https://example.org/experiences/1',
            source_kind='work',title='عنوان محرمانه',body='متن محرمانه برای مدیران',content_sha256='a'*64,
            copyright_review='approved',company_attribution_status='verified',independence_status='verified')
        cls.ai = AiAssessment.objects.create(experience=cls.exp,criteria_version='five_v1',model_name='test',
            prompt_version='v104',run_id='v104',parse_status='imported_provisional')
        for i,(key,label) in enumerate(DIMENSIONS):
            dim=AiDimension.objects.create(assessment=cls.ai,key=key,score=5+i,confidence=80,
                evidence=['شاهد متنی معتبر'],explanation='توضیح سنجش شده')
            AiHumanReviewEvent.objects.create(dimension=dim,reviewer=cls.admin,verdict='supported')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_queue_and_detail(self):
        q=reverse('admin:assessments_aiassessment_publication_queue')
        d=reverse('admin:assessments_aiassessment_publication_detail',args=[self.ai.pk])
        self.assertEqual(self.client.get(q).status_code,200)
        self.assertEqual(self.client.get(d).status_code,200)
        self.assertContains(self.client.get(d),'متن محرمانه برای مدیران')

    def test_publish_and_revoke_with_csrf_ack_and_audit(self):
        url=reverse('admin:assessments_aiassessment_publication_detail',args=[self.ai.pk])
        self.assertFalse(self.ai.publish_approved)
        self.client.post(url,{'action':'publish','rationale':'بازبینی انسانی کافی انجام شده'})
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
        self.client.post(url,{'action':'publish','rationale':'بازبینی انسانی کافی انجام شده','confirmed':'on'})
        self.ai.refresh_from_db();self.assertTrue(self.ai.publish_approved)
        self.assertEqual(LogEntry.objects.filter(object_id=str(self.ai.pk),change_message__contains='PUBLISH_APPROVED').count(),1)
        response=self.client.get(reverse('company-detail',args=[self.company.pk]))
        self.assertContains(response,'ارزیابی‌های تأییدشده')
        self.assertNotContains(response,self.exp.body)
        self.client.post(url,{'action':'revoke','rationale':'نیاز به بررسی دوباره منبع','confirmed':'on'})
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
        self.assertNotContains(self.client.get(reverse('company-detail',args=[self.company.pk])),'ارزیابی‌های تأییدشده')

    def test_gates_prevent_provisional_wrong_and_stale(self):
        self.company.identity_status='unverified';self.company.save(update_fields=['identity_status'])
        self.assertTrue(publication_blockers(self.ai))
        self.company.identity_status='verified';self.company.save(update_fields=['identity_status'])
        self.exp.copyright_review='pending';self.exp.save(update_fields=['copyright_review'])
        self.assertFalse(publication_blockers(self.ai))
        self.exp.copyright_review='blocked';self.exp.save(update_fields=['copyright_review'])
        self.assertTrue(publication_blockers(self.ai))
        self.exp.copyright_review='approved';self.exp.save(update_fields=['copyright_review'])
        first=AiDimension.objects.get(assessment=self.ai,key=DIMENSIONS[0][0])
        AiHumanReviewEvent.objects.create(dimension=first,reviewer=self.admin,verdict='unsupported',
            primary_error='unsupported_score',note='نمره با شواهد متن سازگار نیست')
        self.assertTrue(publication_blockers(self.ai))
        self.assertFalse(public_company_assessments(self.company)['approved_count'])

    def test_public_refuses_wrongly_flagged_rows_and_no_company_mean_for_one(self):
        self.ai.publish_approved=True;self.ai.independent_review_status='approved';
        self.ai.save(update_fields=['publish_approved','independent_review_status'])
        result=public_company_assessments(self.company)
        self.assertEqual(result['approved_count'],1)
        self.assertTrue(all(x['score'] is None for x in result['summary']))
        self.assertFalse(result['has_summary'])
        self.exp.company_attribution_status='rejected';self.exp.save(update_fields=['company_attribution_status'])
        self.assertEqual(public_company_assessments(self.company)['approved_count'],0)

    def test_no_permission_no_publication_and_no_get_mutation(self):
        viewer=get_user_model().objects.create_user(username='v104viewer',password='test',is_staff=True)
        self.client.force_login(viewer)
        url=reverse('admin:assessments_aiassessment_publication_detail',args=[self.ai.pk])
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.post(url,{'action':'publish','confirmed':'on','rationale':'تأیید بررسی کامل'}).status_code,403)
        self.ai.refresh_from_db();self.assertFalse(self.ai.publish_approved)
