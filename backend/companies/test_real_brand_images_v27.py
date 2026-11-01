from pathlib import Path
import json
from django.conf import settings
from django.test import SimpleTestCase

class RealBrandImagesV27Tests(SimpleTestCase):
    def test_curated_domains_and_tosan_photo(self):
        folder=Path(settings.BASE_DIR)/'companies/static/companies'
        manifest=json.loads((folder/'company_images_v27.json').read_text(encoding='utf-8'))
        companies=manifest['companies']
        self.assertGreaterEqual(len(companies),30)
        self.assertEqual(companies['c8a19a54a6e76f538acee']['official_domain'],'snapp.ir')
        self.assertEqual(companies['c6969a729c761f1e232cd']['official_domain'],'digikala.com')
        self.assertTrue((folder/'official_images_v27/tosan_user_supplied.webp').exists())

    def test_unverified_photos_are_not_shown(self):
        folder=Path(settings.BASE_DIR)/'companies/templates/companies'
        for file in ['detail.html','research_five_criteria_v7.html']:
            page=(folder/file).read_text(encoding='utf-8')
            self.assertIn('wi-company-cover-v27',page)
            self.assertNotIn('covers_v26/{{ company.pk }}.webp',page)
        self.assertNotIn('mean_provisional',(folder/'detail.html').read_text(encoding='utf-8'))
