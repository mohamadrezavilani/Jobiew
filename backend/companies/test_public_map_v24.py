"""Public map regression; only verified-company API can populate pins."""
from django.test import SimpleTestCase
from django.urls import reverse


class PublicMapV24Tests(SimpleTestCase):
    def test_map_uses_openfreemap_not_osm_tile_server(self):
        response = self.client.get(reverse('company-map'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'tiles.openfreemap.org/styles/liberty')
        self.assertContains(response, 'maplibre-gl@5.6.0')
        self.assertNotContains(response, 'tile.openstreetmap.org')
        self.assertContains(response, 'persian_digits_v22.js')

    def test_verified_api_is_only_pin_source(self):
        response = self.client.get(reverse('company-map'))
        self.assertContains(response, reverse('verified-company-locations'))
        self.assertContains(response, 'فقط مکان‌هایی نمایش داده می‌شوند')
        self.assertContains(response, 'maplibregl.Marker')
