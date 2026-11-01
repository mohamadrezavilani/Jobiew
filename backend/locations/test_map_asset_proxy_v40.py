"""Regression tests for v40 map proxy and connections. Never contact Internet."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase

from .map_asset_proxy_v39 import safe_asset_path, _safe_redirect, map_connection_mode


class PathsAndRedirects(SimpleTestCase):
    def test_canonical_public_style_path(self):
        self.assertTrue(safe_asset_path('styles/liberty'))
        self.assertEqual(
            _safe_redirect('/styles/liberty/style.json',
                           'https://tiles.openfreemap.org/styles/liberty'),
            'https://tiles.openfreemap.org/styles/liberty/style.json')

    def test_no_open_redirects_or_encoded_traversal(self):
        base = 'https://tiles.openfreemap.org/styles/liberty'
        for redirect in ('https://evil.example/styles/liberty',
                         'http://tiles.openfreemap.org/styles/liberty',
                         '//evil.example/styles/liberty',
                         '/styles/%2e%2e/private',
                         '/styles/liberty?token=foo'):
            self.assertIsNone(_safe_redirect(redirect, base), redirect)
        self.assertFalse(safe_asset_path('styles/%2E%2e/private'))

    def test_mode_is_explicit_or_from_available_proxy(self):
        with patch.dict('os.environ', {'WI_MAP_CONNECTION': 'direct'}):
            self.assertEqual(map_connection_mode(), 'direct')
        with patch.dict('os.environ', {'WI_MAP_CONNECTION': 'proxy'}):
            self.assertEqual(map_connection_mode(), 'proxy')


class MapProxyEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser('testmap40', 'map40@invalid.example', 'test_password')
        self.client.force_login(self.user)

    def test_canonical_route_and_cache(self):
        with patch('locations.map_asset_proxy_v39.fetch_asset',
                   return_value=(200, b'{"version":8}', 'application/json')) as get:
            for _ in range(2):
                r = self.client.get('/admin-map-assets/styles/liberty')
                self.assertEqual(r.status_code, 200)
            get.assert_called_once_with('styles/liberty')

    def test_upstream_status_diagnostic_without_secret(self):
        with patch('locations.map_asset_proxy_v39.fetch_asset', return_value=(403, None, None)):
            r = self.client.get('/admin-map-assets/styles/liberty')
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r['X-WI-Map-Upstream-Status'], '403')
        self.assertNotIn(b'socks5', r.content)
        self.assertNotIn(b'password', r.content)
