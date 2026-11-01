"""Staff-only fixed-origin OpenFreeMap proxy (v40).

No OSM Foundation tile server is accessed. This module never logs proxy
credentials and does not silently switch egress routes on upstream 403/429.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.http import require_GET

UPSTREAM = 'https://tiles.openfreemap.org/'
PROVIDER_HOST = 'tiles.openfreemap.org'
MAX_RESPONSE = 2_500_000
MAX_REDIRECTS = 3
ALLOWED_PATH_ROOTS = frozenset(('styles', 'planet', 'fonts', 'tiles', 'data', 'sprites', 'natural_earth'))
ALLOWED_MIME = frozenset((
    'application/json', 'application/vnd.mapbox-vector-tile',
    'application/x-protobuf', 'application/octet-stream',
    'image/png', 'image/jpeg', 'image/webp', 'image/svg+xml',
    'application/x-font-woff', 'font/woff', 'font/woff2', 'application/font-woff',
))


def safe_asset_path(path):
    if not isinstance(path, str) or not path or len(path) > 350:
        return False
    decoded = unquote(path)
    if '\\' in decoded or '?' in decoded or '#' in decoded or '\x00' in decoded:
        return False
    if decoded in ('planet', 'styles/liberty'):
        return True
    sections = decoded.split('/')
    if len(sections) < 2 or sections[0] not in ALLOWED_PATH_ROOTS:
        return False
    if any(part in ('', '.', '..') for part in sections):
        return False
    if any(':' in part or '<' in part or '>' in part for part in sections):
        return False
    return True


def _read_local_proxy_env(project_root):
    """Read existing private local proxy URL; never expose it in responses."""
    paths = (
        project_root / 'data' / 'map_proxy.env',
        project_root.parent / 'tajrobewiki_crawler' / 'data' / 'anthropic_local.env',
    )
    for path in paths:
        try:
            if not path.is_file():
                continue
            for raw in path.read_text(encoding='utf-8-sig').splitlines():
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                if key.strip() in ('MAP_PROXY_URL', 'PROXY_URL') and value.strip():
                    return value.strip().strip('"\'')
        except (OSError, UnicodeError):
            continue
    return None


def _project_root():
    return Path(__file__).resolve().parents[1]


def map_proxy_url():
    return (os.environ.get('WI_MAP_PROXY_URL') or os.environ.get('MAP_PROXY_URL')
            or _read_local_proxy_env(_project_root()))


def map_connection_mode():
    """Use proxy if configured unless explicitly switched to direct."""
    explicit = os.environ.get('WI_MAP_CONNECTION', '').strip().lower()
    if explicit not in ('direct', 'proxy'):
        path = _project_root() / 'data' / 'map_connection_mode.txt'
        try:
            explicit = path.read_text(encoding='ascii').strip().lower()
        except (OSError, UnicodeError):
            explicit = ''
    if explicit in ('direct', 'proxy'):
        return explicit
    return 'proxy' if map_proxy_url() else 'direct'


def _safe_redirect(location, current_url):
    """Reject any redirect away from fixed HTTPS origin or to unsafe paths."""
    new = urlsplit(urljoin(current_url, location))
    if (new.scheme != 'https' or new.hostname != PROVIDER_HOST
            or new.port not in (None, 443) or new.username or new.password
            or new.query or new.fragment):
        return None
    path = unquote(new.path.lstrip('/'))
    if not safe_asset_path(path):
        return None
    return UPSTREAM + path


def rewrite_provider_urls(payload, *, local_prefix='/admin-map-assets/'):
    """Rewrite OpenFreeMap resource URLs in StyleJSON and TileJSON.

    ``local_prefix`` must be an absolute origin URL when the resulting JSON is
    delivered to MapLibre.  MapLibre requires absolute Sprite/Tile URLs (even
    though the browser normally accepts root-relative paths).
    The default preserves the old helper API for internal regression tests;
    the Django endpoint ALWAYS passes request.build_absolute_uri(...).

    Unrelated external hosts are not changed or proxied.
    """
    doc = json.loads(payload)
    if not isinstance(doc, dict):
        raise ValueError('not a JSON object')
    def local_url(value):
        if not isinstance(value, str):
            return value
        parts = urlsplit(value)
        if (parts.scheme == 'https' and parts.hostname == PROVIDER_HOST and
                parts.port in (None, 443) and not parts.username and
                not parts.password and not parts.query and not parts.fragment):
            path = unquote(parts.path.lstrip('/'))
            if safe_asset_path(path):
                return local_prefix + path
        return value
    def visit(node):
        if isinstance(node, dict):
            return {key: (local_url(value) if key in ('url', 'sprite', 'glyphs') else
                          [local_url(x) for x in value] if key == 'tiles' and isinstance(value, list) else
                          visit(value)) for key, value in node.items()}
        if isinstance(node, list):
            return [visit(x) for x in node]
        return node
    return json.dumps(visit(doc), ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def fetch_asset(asset_path, *, mode=None):
    """Return (upstream-status, response-bytes-or-None, MIME-or-None).

    Follows max 3 redirects only to approved paths on same upstream host.
    Does not retry a provider's 403/429 via a different route.
    """
    import httpx
    if not safe_asset_path(asset_path):
        return 400, None, None
    mode = mode or map_connection_mode()
    if mode not in ('proxy', 'direct'):
        raise ValueError('invalid map connection mode')
    proxy = map_proxy_url() if mode == 'proxy' else None
    if mode == 'proxy' and not proxy:
        return 503, None, None
    headers = {
        'User-Agent': 'WorkplaceInsights-AdminMap/0.40 (OpenFreeMap display; local development)',
        'Accept': 'application/json,image/*,application/x-protobuf,*/*;q=0.5',
    }
    # No ambient HTTP(S)_PROXY: mode is deterministic and private settings win.
    with httpx.Client(proxy=proxy, timeout=15.0, follow_redirects=False,
                      trust_env=False) as client:
        url = UPSTREAM + asset_path
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream('GET', url, headers=headers) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    target = _safe_redirect(response.headers.get('location', ''), url)
                    if target is None:
                        return 502, None, None
                    url = target
                    continue
                if response.status_code != 200:
                    return response.status_code, None, None
                mimetype = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if mimetype not in ALLOWED_MIME:
                    return 415, None, None
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        return 413, None, None
                return 200, bytes(data), mimetype
    return 508, None, None


@require_GET
@staff_member_required
def map_asset(request, asset_path):
    if not safe_asset_path(asset_path):
        return HttpResponse(status=400)
    mode = map_connection_mode()
    key = 'wi_map42_raw:' + hashlib.sha256(f'{mode}:{asset_path}'.encode()).hexdigest()
    result = cache.get(key)
    if result is None:
        try:
            code, payload, mime = fetch_asset(asset_path)
        except Exception:
            return HttpResponse('Map connection failed (check direct/proxy diagnostic)',
                                status=502, content_type='text/plain; charset=utf-8')
        if code != 200:
            response = HttpResponse('Map upstream HTTP ' + str(int(code)) +
                                    ' (run diagnose_map_v40 for details)',
                                    status=502, content_type='text/plain; charset=utf-8')
            response['X-WI-Map-Upstream-Status'] = str(int(code))
            return response
        # Cache upstream ORIGINAL bytes. Absolute URLs are tied to the current
        # request host/scheme and must never be shared across different hosts.
        result = (payload, mime)
        cache.set(key, result, 3600)
    body, mimetype = result
    if mimetype == 'application/json':
        try:
            # Sprite, tiles and glyph templates must be ABSOLUTE for MapLibre.
            # Django validates the Host header when build_absolute_uri runs.
            origin_prefix = request.build_absolute_uri('/admin-map-assets/')
            body = rewrite_provider_urls(body, local_prefix=origin_prefix)
        except (ValueError, TypeError, UnicodeError):
            return HttpResponse('Upstream map JSON is invalid', status=502,
                                content_type='text/plain')
    answer = HttpResponse(body, content_type=mimetype)
    answer['Cache-Control'] = 'private, max-age=3600'
    answer['X-Content-Type-Options'] = 'nosniff'
    return answer
