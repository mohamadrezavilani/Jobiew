"""Static admin contrast regression tests; no third-party API calls or DB changes."""
from pathlib import Path
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import SimpleTestCase


def _relative_luminance(rgb):
    channels = []
    for x in rgb:
        v = x / 255
        channels.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(bg, fg):
    a, b = _relative_luminance(bg), _relative_luminance(fg)
    return (max(a, b) + .05) / (min(a, b) + .05)


class JobiewAdminContrastTests(SimpleTestCase):
    def test_contrast_pairs_are_legible(self):
        for bg in [(0x14, 0x56, 0x6f), (0x10, 0x3f, 0x55),
                   (0x52, 0x62, 0x73), (0x9f, 0x26, 0x36)]:
            with self.subTest(bg=bg):
                self.assertGreaterEqual(_contrast(bg, (255, 255, 255)), 4.5)

    def test_shared_font_stylesheet_includes_complete_contrast_fix(self):
        path = finders.find('companies/css/jobiew_vazir_v110.css')
        self.assertTrue(path)
        css = Path(path).read_text(encoding='utf-8')
        self.assertEqual(css.count('JOBIEW_ADMIN_CONTRAST_V1122_BEGIN'), 1)
        self.assertEqual(css.count('JOBIEW_ADMIN_CONTRAST_V1122_END'), 1)
        self.assertIn('.wi-x .wi-x-claude-shortcut a.button', css)
        self.assertIn('.jr .jr-button.jr-primary', css)
        self.assertIn('button:disabled', css)
        self.assertIn('.deletelink', css)
        self.assertIn('color: #ffffff !important', css)

    def test_admin_inherits_shared_font_and_contrast_css(self):
        template = get_template('admin/base_site.html')
        contents = Path(template.origin.name).read_text(encoding='utf-8')
        self.assertIn('jobiew_vazir_v110.css', contents)

    def test_claude_shortcut_is_present(self):
        template = get_template('admin/companies/company/experience_detail_v103.html')
        contents = Path(template.origin.name).read_text(encoding='utf-8')
        self.assertIn('wi-x-claude-shortcut', contents)
