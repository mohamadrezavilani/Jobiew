"""Regression guards for view-only digit normalization (no database writes)."""
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase


TEMPLATES = (
    'index.html',
    'detail.html',
    'map.html',
    'research_five_criteria_v7.html',
    'research_five_criteria_compare_v12.html',
    'research_five_criteria_analytics_v13.html',
)


class PersianDigitsV22Tests(SimpleTestCase):
    def test_pages_load_one_visual_only_localizer(self):
        root = Path(settings.BASE_DIR) / 'companies' / 'templates' / 'companies'
        for name in TEMPLATES:
            with self.subTest(template=name):
                html = (root / name).read_text(encoding='utf-8')
                self.assertIn('{% load static %}', html)
                self.assertEqual(html.count('persian_digits_v22.js'), 1)
                self.assertIn('{% static "companies/js/persian_digits_v22.js" %}', html)

    def test_script_excludes_machine_readable_content(self):
        path = Path(settings.BASE_DIR) / 'companies' / 'static' / 'companies' / 'js' / 'persian_digits_v22.js'
        js = path.read_text(encoding='utf-8')
        self.assertIn("'SCRIPT'", js)
        self.assertIn("'STYLE'", js)
        self.assertIn("'TEXTAREA'", js)
        self.assertIn('isContentEditable', js)
        self.assertIn('NodeFilter.SHOW_TEXT', js)
        self.assertIn('MutationObserver', js)
        self.assertNotIn('value =', js)
