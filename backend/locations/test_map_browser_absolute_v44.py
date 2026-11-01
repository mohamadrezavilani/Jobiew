"""v0.44: Browser MapLibre must never receive relative proxied URL templates."""
from pathlib import Path
from django.test import SimpleTestCase


class MapBrowserUrlTransformTests(SimpleTestCase):
    @staticmethod
    def script():
        return (Path(__file__).resolve().parent / 'static' / 'locations' / 'js' / 'location_picker_v39.js').read_text(encoding='utf-8')

    def test_map_style_uses_absolute_origin(self):
        script = self.script()
        self.assertIn("const absoluteProxyBase=new URL(prefix,window.location.origin).href;", script)
        self.assertIn("style:absoluteProxyBase+'styles/liberty'", script)

    def test_transform_never_returns_a_relative_provider_asset(self):
        script = self.script()
        self.assertIn("return {url:absoluteProxyBase+u.pathname.replace", script)
        self.assertIn("if(u.origin===window.location.origin && u.pathname.startsWith(prefix))", script)
        self.assertIn("return {url:u.href};", script)
        self.assertNotIn("return {url:prefix+u.pathname", script)

    def test_diagnostic_button_remains(self):
        self.assertIn("diagnostic.textContent='بررسی فایل‌های نقشه'", self.script())
