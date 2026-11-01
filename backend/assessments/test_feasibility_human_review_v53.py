import csv
import json
import tempfile
from io import StringIO
from pathlib import Path
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent
from assessments.review_workspace_v53 import build_metrics
from companies.models import Company
from experiences.models import PublicExperience


class HumanFeasibilityReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(id='v53company',source_url='https://example.org/company',
                                              source_name='Test',display_name='شرکت نمونه')
        cls.experience = PublicExperience.objects.create(company=cls.company,
            source_url='https://example.org/experience', source_kind='work',
            title='نظر واقعی آزمایشی', body='پرداخت حقوق به موقع است اما حقوق نسبت به بازار بررسی نشده است.',
            content_sha256='a'*64)
        cls.assessment = AiAssessment.objects.create(experience=cls.experience,
            model_name='historical-no-new-api',prompt_version='v1',run_id='v53-test',criteria_version='legacy9')
        cls.present = AiDimension.objects.create(assessment=cls.assessment,
            key='workload',score=2,confidence=91,evidence=[{'quote':'حقوق'}],explanation='توضیح AI')
        cls.absent = AiDimension.objects.create(assessment=cls.assessment,
            key='market_pay_competitiveness',score=None,confidence=0,evidence=[],explanation='')
        cls.admin = get_user_model().objects.create_superuser('admin53','admin53@example.org','testPass123')
        cls.staff = get_user_model().objects.create_user('staff53','staff53@example.org','testPass123', is_staff=True)
        cls.url = reverse('admin:assessments_aiassessment_feasibility_review')

    def test_requires_authenticated_staff_and_view_permission(self):
        self.assertEqual(self.client.get(self.url).status_code,302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code,403)
        view = Permission.objects.get(codename='view_aiassessment')
        self.staff.user_permissions.add(view)
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertContains(self.client.get(self.url),'نظر واقعی آزمایشی')
        self.assertFalse(AiHumanReviewEvent.objects.exists())

    def test_staff_view_permission_cannot_write_without_add_permission(self):
        self.staff.user_permissions.add(Permission.objects.get(codename='view_aiassessment'))
        self.client.force_login(self.staff)
        post = self._post(self.present,'supported')
        self.assertEqual(self.client.post(self.url+'?assessment='+str(self.assessment.pk),post).status_code,403)
        self.assertEqual(AiHumanReviewEvent.objects.count(),0)

    def _post(self,dim,verdict,primary_error='',note='',ack='on'):
        payload={'assessment_id':str(self.assessment.pk),'dimension_id':str(dim.pk),
                 'verdict':verdict,'primary_error':primary_error,'note':note}
        if ack:
            payload['acknowledged_source']=ack
        return payload

    def test_supported_review_creates_event_without_changing_ai_scores_or_publishing(self):
        self.client.force_login(self.admin)
        response=self.client.post(self.url+'?assessment='+str(self.assessment.pk), self._post(self.present,'supported'))
        self.assertEqual(response.status_code,302)
        e=AiHumanReviewEvent.objects.get()
        self.assertEqual(e.reviewer,self.admin)
        self.present.refresh_from_db();self.assessment.refresh_from_db()
        self.assertEqual(self.present.score,2)
        self.assertEqual(self.present.semantic_status,'unreviewed')
        self.assertFalse(self.assessment.publish_approved)
        self.assertEqual(self.assessment.independent_review_status,'unreviewed')

    def test_error_must_have_category_and_description(self):
        self.client.force_login(self.admin)
        r=self.client.post(self.url+'?assessment='+str(self.assessment.pk),self._post(self.present,'unsupported'))
        self.assertEqual(r.status_code,200)
        self.assertContains(r,'نوع خطا را انتخاب کنید')
        self.assertEqual(AiHumanReviewEvent.objects.count(),0)
        r=self.client.post(self.url+'?assessment='+str(self.assessment.pk),
                           self._post(self.present,'unsupported','wrong_dimension','این دسته‌بندی اشتباه است'))
        self.assertEqual(r.status_code,302)
        self.assertEqual(AiHumanReviewEvent.objects.get().primary_error,'wrong_dimension')

    def test_cannot_approve_a_missing_score_as_supported(self):
        self.client.force_login(self.admin)
        r=self.client.post(self.url+'?assessment='+str(self.assessment.pk),
                           self._post(self.absent,'supported'))
        self.assertEqual(r.status_code,200)
        self.assertEqual(AiHumanReviewEvent.objects.count(),0)
        r=self.client.post(self.url+'?assessment='+str(self.assessment.pk),
                           self._post(self.absent,'correct_abstention'))
        self.assertEqual(r.status_code,302)
        self.assertEqual(AiHumanReviewEvent.objects.get().verdict,'correct_abstention')

    def test_source_review_acknowledgment_required(self):
        self.client.force_login(self.admin)
        r=self.client.post(self.url+'?assessment='+str(self.assessment.pk),
                           self._post(self.present,'supported',ack=''))
        self.assertEqual(r.status_code,200)
        self.assertFalse(AiHumanReviewEvent.objects.exists())

    def test_wrong_dimension_submission_rejected(self):
        other=AiAssessment.objects.create(experience=self.experience,model_name='x',
                            prompt_version='x',run_id='v53-other',criteria_version='legacy9')
        other_dim=AiDimension.objects.create(assessment=other,key='career_growth',score=5,confidence=50)
        self.client.force_login(self.admin)
        r=self.client.post(self.url+'?assessment='+str(self.assessment.pk), self._post(other_dim,'supported'))
        self.assertEqual(r.status_code,404)
        self.assertFalse(AiHumanReviewEvent.objects.exists())

    def test_review_events_append_only_and_latest_counts_once(self):
        AiHumanReviewEvent.objects.create(dimension=self.present,reviewer=self.admin,verdict='supported')
        latest=AiHumanReviewEvent.objects.create(dimension=self.present,reviewer=self.admin,
                verdict='unsupported',primary_error='wrong_polarity',note='جهت امتیازدهی اشتباه شده است')
        with self.assertRaises(ValueError):
            latest.save()
        with self.assertRaises(ValueError):
            latest.delete()
        rows,totals=build_metrics([AiAssessment.objects.prefetch_related('dimensions__human_review_events').get(pk=self.assessment.pk)])
        self.assertEqual(totals['reviewed'],1)
        self.assertEqual(next(x for x in rows if x['key']=='workload')['unsupported'],1)

    def test_does_not_expose_raw_text_to_anonymous_users(self):
        r=self.client.get(self.url+'?assessment='+str(self.assessment.pk))
        self.assertNotIn('حقوق نسبت به بازار',r.content.decode('utf-8'))
        self.client.force_login(self.admin)
        r=self.client.get(self.url+'?assessment='+str(self.assessment.pk))
        self.assertEqual(r.status_code,200)
        self.assertEqual(r['Cache-Control'].find('no-store')>=0,True)
        self.assertContains(r,'پرداخت حقوق به موقع است')

    def test_conflicting_verdict_validated_in_model_even_without_form(self):
        with self.assertRaises(ValidationError):
            AiHumanReviewEvent.objects.create(dimension=self.present,reviewer=self.admin,
                                              verdict='missed_evidence',primary_error='missed_signal',
                                              note='شاهد مشخصی را مدل نادیده گرفته است')

    def test_export_report_counts_no_database_write(self):
        AiHumanReviewEvent.objects.create(dimension=self.present,reviewer=self.admin,
            verdict='unsupported',primary_error='wrong_dimension',note='این متن به شاخص دیگری مرتبط است')
        AiHumanReviewEvent.objects.create(dimension=self.absent,reviewer=self.admin,
            verdict='correct_abstention')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'quality'
            call_command('feasibility_human_quality_v53',out=str(out),stdout=StringIO())
            obj=json.loads((out/'manifest.json').read_text('utf-8'))
            self.assertEqual(obj['reviewed_latest'],2)
            self.assertEqual(obj['error_count'],1)
            self.assertEqual(obj['database_writes'],0)
            with (out/'dimension_quality.csv').open(encoding='utf-8-sig') as f:
                data=list(csv.DictReader(f))
            row=next(x for x in data if x['key']=='workload')
            self.assertEqual(row['observed_error_pct'],'100.0')
            self.assertTrue((out/'human_review_latest_PRIVATE.csv').is_file())
            self.assertEqual(AiHumanReviewEvent.objects.count(),2)

    def test_excludes_interviews_from_reviews(self):
        interview=PublicExperience.objects.create(company=self.company,
            source_url='https://example.org/interview', source_kind='interview',title='Interview',body='Private interview',
            content_sha256='b'*64)
        ai=AiAssessment.objects.create(experience=interview,model_name='x',prompt_version='x',run_id='interview')
        self.client.force_login(self.admin)
        r=self.client.get(self.url)
        self.assertNotContains(r,'Private interview')
        self.assertEqual(self.client.get(self.url+f'?assessment={ai.pk}').status_code,404)
