"""Site-wide Vazir typography smoke tests (no DB mutation)."""
from pathlib import Path
from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import SimpleTestCase


class JobiewVazirTests(SimpleTestCase):
    def test_all_public_templates_reference_shared_font(self):
        names = [
            'companies/index.html',
            'companies/detail.html',
            'companies/map.html',
            'companies/research_five_criteria_v7.html',
            'companies/research_five_criteria_compare_v12.html',
            'companies/research_five_criteria_analytics_v13.html',
        ]
        for name in names:
            with self.subTest(name=name):
                template = get_template(name)
                content = Path(template.origin.name).read_text(encoding='utf-8')
                self.assertEqual(content.count('jobiew_vazir_v110.css'), 1)

    def test_font_stylesheet_is_static(self):
        resource = finders.find('companies/css/jobiew_vazir_v110.css')
        self.assertTrue(resource)
        content = Path(resource).read_text(encoding='utf-8')
        self.assertIn("font-family: 'Vazir'", content)
        self.assertIn('Vazir-Regular.woff2', content)
        self.assertNotIn('font:15px/1.85 Tahoma', content)

    def test_django_admin_base_site_includes_font(self):
        template = get_template('admin/base_site.html')
        self.assertIn('base_site.html', Path(template.origin.name).name)
        body = Path(template.origin.name).read_text(encoding='utf-8')
        self.assertIn('jobiew_vazir_v110.css', body)
        self.assertIn('admin/base.html', body)
