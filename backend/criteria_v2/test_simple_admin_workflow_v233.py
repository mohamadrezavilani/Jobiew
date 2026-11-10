"""Synthetic admin landing and per-company next-step regression."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company, CompanyVerificationEvent
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import CriteriaAnalysis, CriteriaScoreReviewEvent, ClaudeSixCheck
from criteria_v2.registry import axes_for
from experiences.models import PublicExperience

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED':'1',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED':'0',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST':'jobiew.ir',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED':'0',
    'JOBIEW_ADMIN_FOCUSED_WORKFLOW_ENABLED':'1',
}
BODY = ('پرداخت حقوق در موعد مقرر انجام شد و قرارداد روشن بود. '
        'دربارهٔ بقیه معیارها شاهدی ندارم.')
QUOTE = 'پرداخت حقوق در موعد مقرر انجام شد'


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['jobiew.ir','testserver'],
                   CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https'))
class SimpleAdminWorkflowV233Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(
            id='workflow-v233', source_name='test',
            source_url='https://example.invalid/wf',
            display_name='شرکت آزمون مدیریت ساده')
        cls.user=get_user_model().objects.create_superuser(
            username='workflow-v233-admin', password='test-only',
            email='workflow233@example.invalid')
        cls.exp=PublicExperience.objects.create(
            company=cls.company, source_kind='work',
            source_url='https://example.invalid/story',
            title='رکورد ساختگی', body=BODY, content_sha256='3'*64)
        cls.not_scored=PublicExperience.objects.create(
            company=cls.company, source_kind='interview',
            source_url='https://example.invalid/other',
            title='بدون امتیاز GPT-6', body='تجربه مصاحبهٔ دیگر',
            content_sha256='4'*64)
        dimensions={}
        for i,axis in enumerate(axes_for('work')):
            dimensions[axis.key]=({
                'score':7, 'confidence':90, 'evidence':QUOTE,
                'explanation':'شاهد پرداخت منظم در تجربه موجود است'
            } if i==0 else {
                'score':None,'confidence':0,'evidence':'',
                'explanation':'در متن روایت شاهد کافی برای این معیار نیست'
            })
        stage_one({
            'experience_id':cls.exp.pk, 'company_id':cls.company.pk,
            'kind':'work','source_content_sha256':cls.exp.content_sha256,
            'story_sha256':story_digest(story_from_experience(cls.exp)),
            'review_status':'unverified_private_proposal',
            'model_name':'GPT-6-synthetic',
            'prediction':{'detected_kind':'work','kind_confidence':90,
                          'dimensions':dimensions},
        })

    def setUp(self):
        self.client=Client()
        self.client.force_login(self.user)
        self.workflow=reverse('admin:companies_company_workflow',
                              args=[self.company.pk])

    def get(self,url, flags=None):
        with patch.dict('os.environ',flags if flags is not None else FLAGS):
            return self.client.get(url,secure=True,HTTP_HOST='jobiew.ir')

    def test_home_is_task_oriented_and_preserves_audit_access(self):
        home=self.get(reverse('admin:index'))
        self.assertEqual(home.status_code,200)
        self.assertContains(home,'از دریافت تجربه تا انتشار امتیاز')
        self.assertContains(home,'پیدا کردن شرکت')
        self.assertContains(home,'پروندهٔ شش‌معیاری')
        self.assertContains(home,'امکانات فنی و تاریخچهٔ حسابرسی')
        self.assertEqual(home.context['jw_counts']['checkpoint'],1)
        self.assertEqual(home.context['jw_counts']['experiences'],2)
        self.assertNotContains(home,'دستورالعمل پنج معیار')

    def test_company_step_and_existing_audits_are_visible(self):
        page=self.get(self.workflow)
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['total_experiences'],2)
        self.assertEqual(page.context['unscored_experiences'],1)
        self.assertEqual(page.context['counts']['pending'],1)
        self.assertEqual(page.context['next']['label'],
                         '۲. بازبینی شش‌معیاری GPT-6')
        self.assertContains(page,'تأییدهای انجام‌شده باقی می‌مانند')
        self.assertContains(page,'هنوز در checkpointهای شش‌معیاری')
        self.assertContains(page,reverse(
            'admin:companies_company_checkpoint_bulk',
            args=[self.company.pk]))
        queue=self.get(reverse('admin:companies_company_checkpoint_queue'))
        self.assertContains(queue,'ادامهٔ کار')
        self.assertContains(queue,self.workflow)
        cl=self.get(reverse('admin:companies_company_changelist'))
        self.assertContains(cl,'وضعیت و قدم بعدی')
        self.assertContains(cl,'داشبورد بررسی')
        change=self.get(reverse('admin:companies_company_change',args=[self.company.pk]))
        self.assertContains(change,self.workflow)
        self.assertContains(change,'ورود به داشبورد بررسی همین شرکت')
        self.assertFalse(CriteriaScoreReviewEvent.objects.exists())

    def test_no_checkpoint_does_not_falsely_claim_publication_complete(self):
        co=Company.objects.create(id='v233-empty-co',display_name='شرکت بدون تجربه',
            source_url='https://example.invalid/empty',source_name='synthetic')
        page=self.get(reverse('admin:companies_company_workflow',args=[co.pk]))
        self.assertEqual(page.context['total_experiences'],0)
        self.assertEqual(page.context['next']['label'],'۱. دریافت تجربه‌ها')
        self.assertFalse(page.context['steps'][-1]['complete'])
        self.assertFalse(ClaudeSixCheck.objects.exists())

    def test_strict_permissions_and_private_gate(self):
        visitor=get_user_model().objects.create_user(
            username='v233-limited',is_staff=True,password='unused')
        visitor.user_permissions.add(Permission.objects.get(
            content_type__app_label='companies',codename='view_company'))
        cl=Client()
        cl.force_login(visitor)
        with patch.dict('os.environ',FLAGS):
            resp=cl.get(self.workflow,secure=True,HTTP_HOST='jobiew.ir')
        self.assertEqual(resp.status_code,403)
        with patch.dict('os.environ',{
            **FLAGS,'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED':'0'}):
            disabled=self.client.get(self.workflow,secure=True,HTTP_HOST='jobiew.ir')
        self.assertEqual(disabled.status_code,404)
        self.assertFalse(ClaudeSixCheck.objects.exists())
