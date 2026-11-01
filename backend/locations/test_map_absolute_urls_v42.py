"""v0.42: MapLibre resource URLs must be fully-qualified. No network calls."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from locations.map_asset_proxy_v39 import rewrite_provider_urls

PREFIX = 'http://testserver/admin-map-assets/'


class FullURLRewriteTests(SimpleTestCase):
    def test_absolute_sprite_glyphs_and_vector_raster_tile_templates(self):
        incoming = {
            'version': 8,
            'sprite': 'https://tiles.openfreemap.org/sprites/ofm_f384/ofm',
            'glyphs': 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
            'sources': {
                'vector': {'url': 'https://tiles.openfreemap.org/planet'},
                'raster': {'tiles': ['https://tiles.openfreemap.org/natural_earth/ne2sr/{z}/{x}/{y}.png']},
                'thirdparty': {'url': 'https://elsewhere.invalid/planet'},
            },
        }
        result = json.loads(rewrite_provider_urls(json.dumps(incoming).encode(), local_prefix=PREFIX))
        self.assertEqual(result['sprite'], PREFIX + 'sprites/ofm_f384/ofm')
        self.assertEqual(result['glyphs'], PREFIX + 'fonts/{fontstack}/{range}.pbf')
        self.assertEqual(result['sources']['vector']['url'], PREFIX + 'planet')
        self.assertEqual(result['sources']['raster']['tiles'][0], PREFIX + 'natural_earth/ne2sr/{z}/{x}/{y}.png')
        self.assertEqual(result['sources']['thirdparty']['url'], 'https://elsewhere.invalid/planet')

    def test_tilejson_vector_templates_absolute(self):
        doc = {'tiles': ['https://tiles.openfreemap.org/planet/20261011_080001_pt/{z}/{x}/{y}.pbf']}
        obj = json.loads(rewrite_provider_urls(json.dumps(doc).encode(), local_prefix=PREFIX))
        self.assertEqual(obj['tiles'][0], PREFIX + 'planet/20261011_080001_pt/{z}/{x}/{y}.pbf')


class MapLibreIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_superuser('mapv42', 'mapv42@example.invalid', 'local-secret')
        self.client.force_login(user)

    def test_style_and_tilejson_absolute_on_wire_and_cache_reused(self):
        style = json.dumps({
            'version': 8, 'layers': [],
            'sprite': 'https://tiles.openfreemap.org/sprites/ofm_f384/ofm',
            'glyphs': 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
            'sources': {'streets': {'url': 'https://tiles.openfreemap.org/planet'}},
        }).encode()
        tilejson = json.dumps({'tiles': ['https://tiles.openfreemap.org/planet/20261011_080001_pt/{z}/{x}/{y}.pbf']}).encode()
        with patch('locations.map_asset_proxy_v39.fetch_asset', side_effect=[
                (200, style, 'application/json'), (200, tilejson, 'application/json')]) as mocked:
            a = self.client.get('/admin-map-assets/styles/liberty')
            self.assertEqual(a.status_code, 200)
            data = json.loads(a.content)
            self.assertEqual(data['sprite'], PREFIX + 'sprites/ofm_f384/ofm')
            self.assertEqual(data['glyphs'], PREFIX + 'fonts/{fontstack}/{range}.pbf')
            self.assertEqual(data['sources']['streets']['url'], PREFIX + 'planet')
            b = self.client.get('/admin-map-assets/planet')
            self.assertEqual(b.status_code, 200)
            self.assertEqual(json.loads(b.content)['tiles'][0], PREFIX + 'planet/20261011_080001_pt/{z}/{x}/{y}.pbf')
            again = self.client.get('/admin-map-assets/styles/liberty')
            self.assertEqual(json.loads(again.content)['sprite'], PREFIX + 'sprites/ofm_f384/ofm')
            self.assertEqual(mocked.call_count, 2)

    @override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
    def test_cached_json_not_bound_to_wrong_host(self):
        payload = b'{"sprite":"https://tiles.openfreemap.org/sprites/ofm_f384/ofm"}'
        with patch('locations.map_asset_proxy_v39.fetch_asset', return_value=(200, payload, 'application/json')) as mocked:
            a = self.client.get('/admin-map-assets/styles/liberty', HTTP_HOST='testserver')
            b = self.client.get('/admin-map-assets/styles/liberty', HTTP_HOST='localhost')
        self.assertEqual(json.loads(a.content)['sprite'], 'http://testserver/admin-map-assets/sprites/ofm_f384/ofm')
        self.assertEqual(json.loads(b.content)['sprite'], 'http://localhost/admin-map-assets/sprites/ofm_f384/ofm')
        mocked.assert_called_once()

    def test_no_anonymous_access(self):
        self.client.logout()
        resp = self.client.get('/admin-map-assets/styles/liberty')
        self.assertEqual(resp.status_code, 302)
