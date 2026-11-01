"""v41 regression tests; no live map requests."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from locations.map_asset_proxy_v39 import rewrite_provider_urls, safe_asset_path
from locations.management.commands.diagnose_map_v41 import provider_path, tehran_tile_path


class MapUrlRewriteTests(SimpleTestCase):
    def test_rewrite_full_resource_chain_but_not_unrelated_hosts(self):
        src = {
            'version': 8,
            'glyphs': 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
            'sprite': 'https://tiles.openfreemap.org/sprites/ofm_f384/ofm',
            'sources': {
                'streets': {'type': 'vector', 'url': 'https://tiles.openfreemap.org/planet'},
                'shade': {'type': 'raster', 'tiles': ['https://tiles.openfreemap.org/natural_earth/ne2sr/{z}/{x}/{y}.png']},
                'untrusted': {'type': 'raster', 'tiles': ['https://another.example/tiles/{z}/{x}/{y}.png']}
            }, 'layers': []
        }
        result = json.loads(rewrite_provider_urls(json.dumps(src).encode()))
        self.assertEqual(result['sources']['streets']['url'], '/admin-map-assets/planet')
        self.assertEqual(result['glyphs'], '/admin-map-assets/fonts/{fontstack}/{range}.pbf')
        self.assertEqual(result['sprite'], '/admin-map-assets/sprites/ofm_f384/ofm')
        self.assertEqual(result['sources']['shade']['tiles'][0], '/admin-map-assets/natural_earth/ne2sr/{z}/{x}/{y}.png')
        self.assertEqual(result['sources']['untrusted']['tiles'][0], 'https://another.example/tiles/{z}/{x}/{y}.png')

    def test_rewrite_vector_tilejson(self):
        data = {'tiles': ['https://tiles.openfreemap.org/planet/20260801/{z}/{x}/{y}.pbf']}
        obj = json.loads(rewrite_provider_urls(json.dumps(data).encode()))
        self.assertEqual(obj['tiles'][0], '/admin-map-assets/planet/20260801/{z}/{x}/{y}.pbf')

    def test_reject_unknown_path_and_redirect(self):
        self.assertFalse(safe_asset_path('other/favicon.ico'))
        self.assertFalse(safe_asset_path('natural_earth/../private'))
        self.assertTrue(safe_asset_path('natural_earth/ne2sr/4/10/6.png'))
        self.assertIsNone(provider_path('https://evil.example/planet'))
        self.assertIn('/10/', tehran_tile_path('planet/{z}/{x}/{y}.pbf'))


class MapProxyIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_superuser('maptest41', 'maptest41@example.invalid', 'test-password')
        self.client.force_login(user)

    def test_serve_rewritten_style_and_tilejson(self):
        # v42 serves absolute URLs, as required by MapLibre, rather than
        # the helper default (root-relative) still tested above.
        style = json.dumps({'version': 8, 'layers': [], 'sources': {
            'base': {'type': 'vector', 'url': 'https://tiles.openfreemap.org/planet'}}}).encode()
        tilejson = json.dumps({'tiles': ['https://tiles.openfreemap.org/planet/10/1/1.pbf']}).encode()
        with patch('locations.map_asset_proxy_v39.fetch_asset', side_effect=[
            (200, style, 'application/json'), (200, tilejson, 'application/json')]):
            r = self.client.get('/admin-map-assets/styles/liberty')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(
                json.loads(r.content)['sources']['base']['url'],
                r.wsgi_request.build_absolute_uri('/admin-map-assets/planet'),
            )
            r2 = self.client.get('/admin-map-assets/planet')
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(
                json.loads(r2.content)['tiles'][0],
                r2.wsgi_request.build_absolute_uri('/admin-map-assets/planet/10/1/1.pbf'),
            )

    def test_unauthenticated_asset_not_public(self):
        self.client.logout()
        r = self.client.get('/admin-map-assets/planet')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])
