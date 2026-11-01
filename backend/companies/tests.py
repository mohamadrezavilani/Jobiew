from django.test import TestCase, Client
from django.urls import reverse
from .models import Company

class CompanyViewsTests(TestCase):
    def test_public_pages_do_not_publish_scores_or_raw_reviews(self):
        Company.objects.create(id='c1',source_url='https://a.example/c',source_name='آزمایش',display_name='آزمایش')
        page=self.client.get('/')
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'آزمایش')
        self.assertNotContains(page,'امتیاز نهایی')
        self.assertEqual(self.client.get('/api/locations.geojson').json()['features'],[])
