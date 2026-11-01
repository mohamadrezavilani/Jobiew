from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from companies.models import Company
from experiences.models import ExperienceReviewEvent, PublicExperience


class ExperienceReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('reviewer', 'r@example.invalid', 'SafePwd123!')
        company = Company.objects.create(id='c30', source_url='https://example.org/co',
            source_name='نمونه', display_name='نمونه')
        self.experience = PublicExperience.objects.create(company=company, source_url='https://example.org/e',
            source_kind='work', title='تجربه', body='private text', content_sha256='abcd')

    def test_per_field_decisions_and_non_publication(self):
        with self.assertRaises(ValidationError):
            ExperienceReviewEvent.objects.create(experience=self.experience, reviewer=self.user,
                review_field='copyright', decision='verified', rationale='توضیح لازم برای بررسی شواهد')
        with self.assertRaises(ValidationError):
            ExperienceReviewEvent.objects.create(experience=self.experience, reviewer=self.user,
                review_field='copyright', decision='approved', rationale='توضیح لازم برای بررسی شواهد')
        event = ExperienceReviewEvent.objects.create(experience=self.experience, reviewer=self.user,
            review_field='attribution', decision='verified', evidence_url='https://example.org/source',
            rationale='نام و صفحه شرکت با متن تجربه تطبیق داده شد')
        self.experience.refresh_from_db()
        self.assertEqual(self.experience.company_attribution_status, 'verified')
        self.assertFalse(self.experience.published_publicly)
        with self.assertRaises(ValueError):
            event.save()

    def test_reviewer_can_record_copyright_block(self):
        ExperienceReviewEvent.objects.create(experience=self.experience, reviewer=self.user,
            review_field='copyright', decision='blocked', rationale='مجوز بازنشر متن تجربه وجود ندارد')
        self.experience.refresh_from_db()
        self.assertEqual(self.experience.copyright_review, 'blocked')
        self.assertFalse(self.experience.published_publicly)

    def test_admin_can_record_attribution_without_publishing(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        page = self.client.get(reverse('admin:experiences_experiencereviewevent_add'))
        self.assertEqual(page.status_code, 200)
        response = self.client.post(reverse('admin:experiences_experiencereviewevent_add'), {
            'experience': self.experience.pk,
            'review_field': 'attribution', 'decision': 'verified',
            'evidence_url': 'https://example.org/company',
            'rationale': 'نام شرکت در متن نظر با منبع اصلی بررسی شد',
            '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        self.experience.refresh_from_db()
        self.assertEqual(self.experience.company_attribution_status, 'verified')
        self.assertFalse(self.experience.published_publicly)
