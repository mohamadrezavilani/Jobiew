"""Current six-axis Claude API is manual, private and independent of publication.

All model outputs are synthetic; tests never contact Anthropic or use real text.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from criteria_v2.engine_v207 import story_digest, story_from_experience
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import stage_one
from criteria_v2.models import ClaudeSixCheck, CriteriaAnalysis, CriteriaCompanyReleaseEvent
from criteria_v2.registry import axes_for
from experiences.models import PublicExperience, ExperienceReviewEvent

FLAGS = {
    'JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED': '1',
    'JOBIEW_CHECKPOINT_STAGING_ENABLED': '0',
    'JOBIEW_CHECKPOINT_PUBLIC_HOST': 'jobiew.ir',
    'JOBIEW_CLAUDE_SIX_ENABLED': '1',
    'JOBIEW_CLAUDE_SIX_LIMIT': '3',
    'JOBIEW_CLAUDE_SIX_MODEL': 'claude-sonnet-5-5',
    'ANTHROPIC_API_KEY': 'SYNTHETIC-CI-NOT-REAL',
    'JOBIEW_DUAL6_PUBLICATION_ENABLED': '0',
}
WORK = ('در شرکت پرداخت حقوق به موقع انجام می‌شد و قرارداد روشن بود. '
        'دربارهٔ سایر شاخص‌ها شواهد و تجربهٔ کافی نداشتم.')
INTERVIEW = ('در جلسهٔ مصاحبه برخورد محترمانه و حرفه‌ای بود و نتیجه را اعلام کردند. '
             'دربارهٔ دیگر جنبه‌ها شاهد کافی ندارم.')
QUOTES = {
    'work': 'پرداخت حقوق به موقع انجام می‌شد',
    'interview': 'برخورد محترمانه و حرفه‌ای بود',
}


@override_settings(
    DEBUG=False, SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['jobiew.ir', 'testserver'],
    CSRF_TRUSTED_ORIGINS=['https://jobiew.ir'],
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class ClaudeSixAdminV233Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='claude-six-company', source_name='synthetic',
            source_url='https://example.invalid/company',
            display_name='شرکت ساختگی Claude')
        cls.other = Company.objects.create(
            id='claude-six-other', source_name='synthetic',
            source_url='https://example.invalid/other',
            display_name='شرکت دیگر')
        cls.superuser = get_user_model().objects.create_superuser(
            username='claude-six-super', email='claude@example.invalid',
            password='not-real')
        cls.exps = {}
        for kind, body in [('work', WORK), ('interview', INTERVIEW)]:
            exp = PublicExperience.objects.create(
                company=cls.company, source_kind=kind,
                source_url='https://example.invalid/' + kind,
                source_site='example.invalid',
                title='مثال شش‌محوری ' + kind, body=body,
                content_sha256=('a' if kind == 'work' else 'b')*64)
            cls.exps[kind] = exp
            dims = {}
            for i, axis in enumerate(axes_for(kind)):
                dims[axis.key] = ({
                    'score': 3, 'confidence': 90,
                    'evidence': QUOTES[kind],
                    'explanation': 'شاهد مستقیم دربارهٔ همین تجربه ثبت شده است'
                } if i == 0 else {
                    'score': None, 'confidence': 0,
                    'evidence': '',
                    'explanation': 'دربارهٔ این معیار شاهد کافی وجود ندارد',
                })
            stage_one({
                'experience_id': exp.pk, 'company_id': cls.company.pk,
                'kind': kind, 'source_content_sha256': exp.content_sha256,
                'story_sha256': story_digest(story_from_experience(exp)),
                'model_name': 'GPT-6-synthetic',
                'review_status': 'unverified_private_proposal',
                'prediction': {'detected_kind': kind,
                               'kind_confidence': 90, 'dimensions': dims},
            })
        cls.foreign = PublicExperience.objects.create(
            company=cls.other, source_kind='work', title='محرمانه',
            source_url='https://example.invalid/foreign',
            body='نظر خصوصی شرکت دیگری است', content_sha256='f'*64)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.superuser)

    def url(self, exp):
        return reverse('admin:companies_company_claude_six',
                       args=[self.company.pk, exp.pk])

    def get(self, exp, flags=None):
        with patch.dict('os.environ', flags if flags is not None else FLAGS):
            return self.client.get(self.url(exp), secure=True, HTTP_HOST='jobiew.ir')

    def post(self, exp, confirmed=True, flags=None):
        data = {'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value}
        if confirmed:
            data['confirm_external'] = 'yes'
        with patch.dict('os.environ', flags if flags is not None else FLAGS):
            return self.client.post(self.url(exp), data, secure=True,
                HTTP_HOST='jobiew.ir',
                HTTP_REFERER='https://jobiew.ir' + self.url(exp))

    def rights(self, exp):
        ExperienceReviewEvent.objects.create(
            experience=exp, reviewer=self.superuser, review_field='copyright',
            decision='approved',
            evidence_url='https://example.invalid/licence-for-vendor',
            rationale='مجوز مستند پردازش خصوصی با سرویس خارجی بررسی شده است.')

    def mock_response(self, kind, *, new_score=4, detected=None):
        dims = {}
        for i, axis in enumerate(axes_for(kind)):
            dims[axis.key] = ({
                'score': new_score, 'confidence': 90,
                'evidence': QUOTES[kind],
                'explanation': 'یک برداشت مستقل با شاهد متنی مستقیم'
            } if i == 0 else {
                'score': None, 'confidence': 0, 'evidence': '',
                'explanation': 'دادهٔ کافی برای سنجش این معیار موجود نیست'
            })
        data = {
            'detected_kind': detected or kind, 'kind_confidence': 90,
            'dimensions': dims,
        }
        return {
            'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': json.dumps(data)}],
            'usage': {'input_tokens': 300, 'output_tokens': 200},
        }

    def test_no_api_without_explicit_vendor_rights_or_opt_in(self):
        exp = self.exps['work']
        page = self.get(exp)
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['rights'])
        self.assertFalse(page.context['can_run'])
        with patch('criteria_v2.claude_six_v233.call_claude') as api:
            denied = self.post(exp)
        self.assertEqual(denied.status_code, 302)
        api.assert_not_called()
        self.assertFalse(ClaudeSixCheck.objects.exists())
        self.rights(exp)
        changed = self.get(exp)
        self.assertTrue(changed.context['can_run'])
        with patch('criteria_v2.claude_six_v233.call_claude') as api:
            not_confirmed = self.post(exp, confirmed=False)
        self.assertEqual(not_confirmed.status_code, 302)
        api.assert_not_called()
        self.assertFalse(ClaudeSixCheck.objects.exists())

    def test_work_independent_comparison_persists_no_rerun_and_no_publication(self):
        exp = self.exps['work']
        self.rights(exp)
        page = self.get(exp)
        self.assertContains(page, 'اجرای یک‌بارهٔ Claude')
        self.assertIn('csrftoken', self.client.cookies)
        with patch('criteria_v2.claude_six_v233.call_claude',
                   return_value=self.mock_response('work')) as api:
            response = self.post(exp)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, self.url(exp))
            repeated = self.post(exp)
            self.assertEqual(repeated.status_code, 302)
            api.assert_called_once()
        self.assertEqual(ClaudeSixCheck.objects.count(), 1)
        run = ClaudeSixCheck.objects.get()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.input_tokens, 300)
        after = self.get(exp)
        self.assertEqual(len(after.context['rows']), 6)
        self.assertContains(after, 'یک برداشت مستقل با شاهد متنی مستقیم')
        self.assertContains(after, 'GPT-6')
        self.assertContains(after, 'Claude')
        self.assertContains(after, 'متفاوت')
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())
        self.assertEqual(CriteriaAnalysis.objects.get(experience=exp).review_status,
                         'pilot_unverified')
        public = self.client.get(reverse('company-detail', args=[self.company.pk]))
        self.assertNotContains(public, 'یک برداشت مستقل با شاهد متنی مستقیم')

    def test_global_experience_admin_offers_six_and_claude_with_persisted_status(self):
        exp = self.exps['work']
        url = reverse('admin:experiences_publicexperience_changelist')
        page = self.get(exp)
        self.assertEqual(page.status_code, 200)
        with patch.dict('os.environ', FLAGS):
            listing = self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, 'متن و شش معیار')
        self.assertContains(listing, 'بررسی اختیاری')
        self.assertContains(listing, self.url(exp))
        self.rights(exp)
        with patch('criteria_v2.claude_six_v233.call_claude',
                   return_value=self.mock_response('work')):
            self.assertEqual(self.post(exp).status_code, 302)
        with patch.dict('os.environ', FLAGS):
            after = self.client.get(url, secure=True, HTTP_HOST='jobiew.ir')
        self.assertContains(after, 'نمایش نتیجهٔ قبلی')
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_interview_uses_six_interview_axes_and_never_five_v1(self):
        exp = self.exps['interview']
        self.rights(exp)
        self.assertEqual(self.get(exp).status_code, 200)
        with patch('criteria_v2.claude_six_v233.call_claude',
                   return_value=self.mock_response('interview')) as api:
            self.assertEqual(self.post(exp).status_code, 302)
            sent = api.call_args.args[0]
            self.assertIn('interview_professional_respect',
                          sent['output_config']['format']['schema']['properties']['dimensions']['properties'])
            self.assertNotIn('work_compensation_fairness',
                             sent['output_config']['format']['schema']['properties']['dimensions']['properties'])
        self.assertContains(self.get(exp), 'احترام و رفتار حرفه‌ای')
        self.assertNotContains(self.get(exp), 'پنج معیار')

    def test_vendor_kind_disagreement_is_private_not_a_score(self):
        exp = self.exps['work']
        self.rights(exp)
        self.get(exp)
        with patch('criteria_v2.claude_six_v233.call_claude',
                   return_value=self.mock_response('work', detected='interview')):
            self.assertEqual(self.post(exp).status_code, 302)
        run = ClaudeSixCheck.objects.get()
        self.assertEqual(run.status, 'needs_review')
        self.assertFalse(run.claude_results)
        self.assertFalse(CriteriaCompanyReleaseEvent.objects.exists())

    def test_disabled_gate_and_csrf_guard_prevent_paid_call(self):
        exp = self.exps['work']
        self.rights(exp)
        self.get(exp)
        with patch('criteria_v2.claude_six_v233.call_claude') as api:
            disabled = self.post(exp, flags={**FLAGS,
                                          'JOBIEW_CLAUDE_SIX_ENABLED': '0'})
            self.assertEqual(disabled.status_code, 302)
            illegal = self.client.post(
                self.url(exp), {'confirm_external':'yes'},
                secure=True, HTTP_HOST='jobiew.ir',
                HTTP_REFERER='https://jobiew.ir' + self.url(exp))
            self.assertEqual(illegal.status_code, 403)
            api.assert_not_called()
        self.assertFalse(ClaudeSixCheck.objects.exists())

    def test_wrong_company_and_limited_staff_cannot_view_private_scores(self):
        foreign = reverse('admin:companies_company_claude_six',
                          args=[self.company.pk, self.foreign.pk])
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(self.client.get(foreign, secure=True,
                          HTTP_HOST='jobiew.ir').status_code, 404)
        user = get_user_model().objects.create_user(
            username='claude-limited', is_staff=True, password='unused')
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label='companies',
                                   codename='view_company'))
        cl = Client()
        cl.force_login(user)
        with patch.dict('os.environ', FLAGS):
            self.assertEqual(cl.get(self.url(self.exps['work']),
                secure=True, HTTP_HOST='jobiew.ir').status_code, 403)

    def test_old_source_snapshot_is_not_shown_as_current(self):
        exp = self.exps['work']
        self.rights(exp)
        self.get(exp)
        with patch('criteria_v2.claude_six_v233.call_claude',
                   return_value=self.mock_response('work')):
            self.assertEqual(self.post(exp).status_code, 302)
        PublicExperience.objects.filter(pk=exp.pk).update(content_sha256='f'*64)
        page = self.get(exp)
        self.assertFalse(page.context['current'])
        self.assertNotContains(page, 'یک برداشت مستقل با شاهد متنی مستقیم')
        self.assertContains(page, 'قابل انتساب نیست')
