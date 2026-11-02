"""Read-only company experience browser security and usability regression tests."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.html import escape

from assessments.models import AiAssessment, AiDimension
from companies.models import Company
from experiences.models import PublicExperience


class CompanyExperiencesAdminV103Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(id='v103-company', source_url='https://example.com/co1',
            source_name='شرکت ۱', display_name='شرکت یک')
        cls.other = Company.objects.create(id='v103-other', source_url='https://example.com/co2',
            source_name='شرکت ۲', display_name='شرکت دو')
        cls.root = get_user_model().objects.create_superuser(username='v103-root',
            email='root@example.invalid', password='not-used-by-tests')
        cls.exp = PublicExperience.objects.create(company=cls.company,
            source_url='https://example.com/experiences/one', source_kind='work',
            title='تجربه محرمانه اصلی', body='دورکاری و فشار کاری بالا در تیم',
            job_title='مهندس نرم‌افزار', content_sha256='a' * 64,
            published_jalali='۱۴۰۵/۰۸/۰۸')
        cls.foreign = PublicExperience.objects.create(company=cls.other,
            source_url='https://example.com/experiences/two', source_kind='interview',
            title='متن سایر شرکت‌ها', body='اطلاعات خصوصی شرکت دیگر', content_sha256='b' * 64)

    def setUp(self):
        self.client.force_login(self.root)
        self.list_url = reverse('admin:companies_company_experiences', args=[self.company.pk])
        self.detail_url = reverse('admin:companies_company_experience_detail', args=[self.company.pk, self.exp.pk])

    def test_company_entry_points_and_scoped_results(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تجربه محرمانه اصلی')
        self.assertNotContains(response, 'اطلاعات خصوصی شرکت دیگر')
        self.assertContains(response, 'دورکاری و فشار کاری')
        self.assertContains(self.client.get(reverse('admin:companies_company_change', args=[self.company.pk])),
                            'مشاهده نظرهای این شرکت')
        self.assertContains(self.client.get(reverse('admin:companies_company_review', args=[self.company.pk])),
                            'مشاهده تجربه‌ها و مصاحبه‌ها')
        self.assertContains(self.client.get(reverse('admin:companies_company_changelist')), 'مشاهده نظرها')

    def test_detail_only_shows_selected_company_and_full_body(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'دورکاری و فشار کاری بالا در تیم')
        self.assertNotContains(response, self.foreign.body)
        foreign_url = reverse('admin:companies_company_experience_detail', args=[self.company.pk, self.foreign.pk])
        self.assertEqual(self.client.get(foreign_url).status_code, 404)
        self.assertEqual(self.client.get(reverse('admin:companies_company_experiences', args=['unknown'])).status_code, 404)

    def test_filters_search_and_invalid_params(self):
        self.assertEqual(self.client.get(self.list_url + '?q=دورکاری').context['page_obj'].paginator.count, 1)
        self.assertEqual(self.client.get(self.list_url + '?kind=interview').context['page_obj'].paginator.count, 0)
        self.assertEqual(self.client.get(self.list_url + '?kind=work').context['page_obj'].paginator.count, 1)
        self.assertEqual(self.client.get(self.list_url + '?copyright=approved').context['page_obj'].paginator.count, 0)
        response = self.client.get(self.list_url + '?kind=unsupported&page=not-a-number')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['kind'], 'all')
        self.assertEqual(response.context['page_obj'].number, 1)

    def test_pagination_is_bounded(self):
        for i in range(21):
            PublicExperience.objects.create(company=self.company,
                source_url=f'https://example.com/experiences/extra-{i}', source_kind='interview',
                title=f'مصاحبه {i}', content_sha256=f'{i:064x}')
        response = self.client.get(self.list_url + '?kind=interview')
        self.assertEqual(len(response.context['page_obj'].object_list), 20)
        self.assertTrue(response.context['page_obj'].has_next())
        next_page = self.client.get(self.list_url + '?kind=interview&page=2')
        self.assertEqual(len(next_page.context['page_obj'].object_list), 1)

    def test_renders_untrusted_text_as_text_not_html(self):
        self.exp.body = '<script>alert(42)</script>، نظر کاربران'
        self.exp.save(update_fields=['body'])
        for url in [self.list_url, self.detail_url]:
            response = self.client.get(url)
            self.assertNotContains(response, '<script>alert(42)</script>')
            self.assertContains(response, escape('<script>alert(42)</script>'))

    def test_get_only_no_mutations(self):
        old = (self.exp.title, self.exp.published_publicly)
        for url in [self.list_url, self.detail_url]:
            self.assertEqual(self.client.post(url, {'published_publicly': 'true'}).status_code, 405)
        self.exp.refresh_from_db()
        self.assertEqual((self.exp.title, self.exp.published_publicly), old)

    def test_staff_permissions_required_to_read_comments(self):
        staff = get_user_model().objects.create_user(username='v103-limited', password='unused', is_staff=True)
        perm = Permission.objects.get(content_type__app_label='companies', codename='view_company')
        staff.user_permissions.add(perm)
        cl = Client()
        cl.force_login(staff)
        self.assertEqual(cl.get(self.list_url).status_code, 403)
        self.assertEqual(cl.get(self.detail_url).status_code, 403)
        self.assertNotContains(cl.get(reverse('admin:companies_company_change', args=[self.company.pk])),
                               'مشاهده نظرهای این شرکت')
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='experiences',
                                                          codename='view_publicexperience'))
        self.assertEqual(cl.get(self.list_url).status_code, 200)
        self.assertEqual(cl.get(self.detail_url).status_code, 200)
        self.assertNotContains(cl.get(self.detail_url), 'ارزیابی‌های AI با نسخهٔ five_v1')

    def test_ai_is_five_v1_and_permission_gated(self):
        live = AiAssessment.objects.create(experience=self.exp, criteria_version='five_v1',
            model_name='test-five', prompt_version='v1', run_id='five', raw_payload={})
        AiDimension.objects.create(assessment=live, key='management_environment',
            score=7, confidence=78, explanation='حمایت مدیر در متن قابل مشاهده است')
        old = AiAssessment.objects.create(experience=self.exp, criteria_version='legacy9',
            model_name='test-old', prompt_version='old', run_id='old', raw_payload={})
        AiDimension.objects.create(assessment=old, key='workload', score=2, confidence=50,
            explanation='قدیمی و خارج از پنج معیار')
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'حمایت مدیر در متن قابل مشاهده است')
        self.assertContains(response, 'کیفیت مدیریت و محیط کاری')
        self.assertNotContains(response, 'قدیمی و خارج از پنج معیار')
        self.assertNotContains(response, 'test-old')
