"""Regression tests: protected, fixed-host proxy; no live network tests."""
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from .map_asset_proxy_v39 import safe_asset_path


class MapProxyTests(TestCase):
    def setUp(self):
        self.url='/admin-map-assets/styles/liberty/style.json'
        self.user=get_user_model().objects.create_superuser('mapv39', 'map39@example.invalid', 'secret123')
        cache.clear()

    def test_not_available_to_anonymous(self):
        response=self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])

    def test_unsafe_paths_rejected(self):
        for path in ('styles/../admin', 'styles/%2e%2e/private', 'https://badhost/test',
                     'styles\\liberty', 'unknown/a', 'styles/x?bad=1'):
            self.assertFalse(safe_asset_path(path),path)

    def test_openfreemap_tilejson_path_is_allowed(self):
        self.assertTrue(safe_asset_path('planet'))

    def test_proxy_calls_only_fixed_host_and_caches(self):
        self.client.force_login(self.user)
        with patch('locations.map_asset_proxy_v39.fetch_asset',return_value=(200,b'{"version":8}', 'application/json')) as fetch:
            for _ in range(2):
                res=self.client.get(self.url)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.content,b'{"version":8}')
            fetch.assert_called_once_with('styles/liberty/style.json')

    def test_upstream_error_is_generic(self):
        self.client.force_login(self.user)
        with patch('locations.map_asset_proxy_v39.fetch_asset',side_effect=Exception('secrets could leak')):
            response=self.client.get(self.url)
        self.assertEqual(response.status_code,502)
        self.assertNotIn(b'secrets',response.content)

    def test_map_admin_uses_new_provider(self):
        self.client.force_login(self.user)
        response=self.client.get(reverse('admin:locations_companylocationreviewevent_add'))
        self.assertContains(response,'location_picker_v39.js')
        self.assertContains(response,'maplibre-gl@5.6.0')
        self.assertNotContains(response,'tile.openstreetmap.org')
