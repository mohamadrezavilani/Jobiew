"""No paid APIs or network used: mocked provider tests for address suggestion."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse


class FakeResponse:
    status_code = 200
    content = b'{"display_name":"\\u062a\\u0647\\u0631\\u0627\\u0646, \\u0648\\u0646\\u06a9, \\u062e\\u06cc\\u0627\\u0628\\u0627\\u0646 \\u0645\\u062b\\u0627\\u0644"}'

    def json(self):
        return {'display_name': 'تهران، ونک، خیابان مثال'}


class FakeClient:
    requests = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeResponse()


class ReverseGeocodeV45Tests(TestCase):
    def setUp(self):
        cache.clear()
        FakeClient.requests = []
        self.url = reverse('admin-location-reverse-v45')
        self.user = get_user_model().objects.create_superuser(
            'reverse-v45-admin', 'reverse-v45@example.invalid', 'test-password')

    def location(self, **extra):
        return self.url, {'lat': '35.715321', 'lon': '51.403421', **extra}

    def test_anonymous_or_nonstaff_cannot_use_endpoint(self):
        url, params = self.location()
        self.assertNotEqual(self.client.get(url, params).status_code, 200)
        staffless = get_user_model().objects.create_user('reverse-v45-user', password='test')
        self.client.force_login(staffless)
        self.assertNotEqual(self.client.get(url, params).status_code, 200)

    @patch('httpx.Client', FakeClient)
    @patch('locations.admin_reverse_geocode_v45.map_connection_mode', return_value='direct')
    def test_returns_persian_suggestion_and_cache_prevents_second_fetch(self, _mode):
        self.client.force_login(self.user)
        url, params = self.location()
        first = self.client.get(url, params)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['approximate'])
        self.assertIn('تهران', first.json()['address'])
        self.assertIn('OpenStreetMap', first.json()['attribution'])
        self.assertEqual(len(FakeClient.requests), 1)
        target, opts = FakeClient.requests[0]
        self.assertEqual(target, 'https://nominatim.openstreetmap.org/reverse')
        self.assertEqual(opts['params']['accept-language'], 'fa')
        self.assertIn('WorkplaceInsights', opts['headers']['User-Agent'])
        second = self.client.get(url, params)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(FakeClient.requests), 1)

    @patch('httpx.Client', FakeClient)
    @patch('locations.admin_reverse_geocode_v45.map_connection_mode', return_value='direct')
    def test_rate_limit_across_different_points(self, _mode):
        self.client.force_login(self.user)
        url, params = self.location()
        self.assertEqual(self.client.get(url, params).status_code, 200)
        params['lat'] = '35.715999'
        blocked = self.client.get(url, params)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked['Retry-After'], '2')
        self.assertEqual(len(FakeClient.requests), 1)

    @patch('httpx.Client', FakeClient)
    def test_invalid_coordinates_never_call_provider(self):
        self.client.force_login(self.user)
        for lat,lon in [('nan','51'), ('91','51'), ('35','-90'),
                        ('not-a-number','51'), ('0','0')]:
            self.assertEqual(self.client.get(self.url, {'lat':lat,'lon':lon}).status_code, 400)
        self.assertFalse(FakeClient.requests)

    @patch('httpx.Client', FakeClient)
    @patch('locations.admin_reverse_geocode_v45.map_connection_mode', return_value='proxy')
    @patch('locations.admin_reverse_geocode_v45.map_proxy_url', return_value='socks5://secret.local:9050')
    def test_existing_proxy_routing_is_used_without_exposing_secret(self, _proxy, _mode):
        self.client.force_login(self.user)
        url, params = self.location()
        r = self.client.get(url, params)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('secret.local', r.content.decode('utf-8'))

    def test_url_is_admin_scoped_not_generic_geocoding(self):
        self.assertIn('admin-location-reverse', self.url)
