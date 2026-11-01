"""Staff-only, click-triggered reverse address SUGGESTIONS for location reviews.

Public Nominatim policy: <=1 upstream request/sec across this application,
identifiable User-Agent, visible OSM attribution, cache, no bulk lookups.
Do not publish the suggestion as independently verified company address.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import os

from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .map_asset_proxy_v39 import map_connection_mode, map_proxy_url

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse'
MAX_PAYLOAD_BYTES = 200_000
CACHE_SECONDS = 86400
RATE_LOCK_SECONDS = 2  # deliberately less than 1 upstream request per second


def _point(request):
    try:
        lat = Decimal(request.GET.get('lat', ''))
        lon = Decimal(request.GET.get('lon', ''))
        if not lat.is_finite() or not lon.is_finite():
            raise ValueError('non-finite coordinates')
        # Iran-only admin feature. Avoid turning a company-review form into a
        # general-purpose address lookup API.
        if not (Decimal('24') <= lat <= Decimal('40') and
                Decimal('43') <= lon <= Decimal('64')):
            raise ValueError('Outside the supported region')
        q = Decimal('0.000001')
        return f'{lat.quantize(q):f}', f'{lon.quantize(q):f}'
    except (InvalidOperation, ValueError, TypeError):
        return None


@never_cache
@require_GET
@staff_member_required
def reverse_address(request):
    """Suggest closest mappable address. Never assert company ownership/location."""
    point = _point(request)
    if point is None:
        return JsonResponse({'message': 'مختصات معتبر داخل ایران لازم است.'}, status=400)
    latitude, longitude = point
    cache_key = 'wi_reverse_v45:' + hashlib.sha256(
        f'{latitude},{longitude}'.encode('ascii')).hexdigest()
    saved = cache.get(cache_key)
    if saved is not None:
        return JsonResponse(saved)

    # One per two seconds per *shared cache*. Production with multiple worker
    # processes must use a shared Redis/Memcached cache; LocMemCache is for dev.
    if not cache.add('wi_reverse_v45_upstream_rate_limit', 'busy', timeout=RATE_LOCK_SECONDS):
        response = JsonResponse({'message': 'کمی صبر کنید و دوباره نقطه را انتخاب کنید.'}, status=429)
        response['Retry-After'] = '2'
        return response

    try:
        import httpx
        proxy = map_proxy_url() if map_connection_mode() == 'proxy' else None
        agent = os.environ.get('WI_NOMINATIM_USER_AGENT') or (
            'WorkplaceInsights-AdminLocationReview/0.45 (staff-only, manual location review)'
        )
        with httpx.Client(proxy=proxy, trust_env=False, follow_redirects=False,
                          timeout=10.0) as client:
            upstream = client.get(
                NOMINATIM_URL,
                params={'lat': latitude, 'lon': longitude, 'format': 'jsonv2',
                        'addressdetails': '1', 'zoom': '18', 'accept-language': 'fa'},
                headers={'User-Agent': agent, 'Accept': 'application/json',
                         'Accept-Language': 'fa'},
            )
        if upstream.status_code != 200:
            return JsonResponse({'message': 'سرویس پیشنهاد نشانی فعلاً در دسترس نیست.'}, status=503)
        if len(upstream.content) > MAX_PAYLOAD_BYTES:
            return JsonResponse({'message': 'پاسخ سرویس نشانی غیرمنتظره بود.'}, status=502)
        value = upstream.json()
        raw = value.get('display_name', '') if isinstance(value, dict) else ''
        address = ' '.join(raw.split())[:500] if isinstance(raw, str) else ''
        if len(address) < 8:
            return JsonResponse({'message': 'برای این نقطه نشانی مناسبی پیدا نشد.'}, status=404)
        result = {
            'address': address,
            'approximate': True,
            'attribution': '© OpenStreetMap contributors — Nominatim',
        }
        cache.set(cache_key, result, CACHE_SECONDS)
        return JsonResponse(result)
    except Exception:
        # Do not echo proxy credentials, request URLs, stack traces, or details.
        return JsonResponse({'message': 'دریافت نشانی ممکن نشد؛ آن را دستی وارد کنید.'}, status=503)
