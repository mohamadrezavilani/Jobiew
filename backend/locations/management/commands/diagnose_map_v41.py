"""Read-only diagnostic for every provider asset needed to draw a Tehran map.

Never reveals map proxy credentials, source URLs or customer data.
"""
import json
import math
from urllib.parse import unquote, urlsplit

from django.core.management.base import BaseCommand
from locations.map_asset_proxy_v39 import (
    PROVIDER_HOST, fetch_asset, map_connection_mode, map_proxy_url, safe_asset_path,
)


def provider_path(url):
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != PROVIDER_HOST or
            parts.username or parts.password or parts.query or parts.fragment or
            parts.port not in (None, 443)):
        return None
    path = unquote(parts.path.lstrip('/'))
    return path if safe_asset_path(path) else None


def tehran_tile_path(template, zoom=10, lon=51.389, lat=35.6892):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n)
    return template.replace('{z}', str(zoom)).replace('{x}', str(x)).replace('{y}', str(y))


def probe(mode, path, label, results):
    try:
        code, body, mime = fetch_asset(path, mode=mode)
        output = {'asset': label, 'http_status': int(code), 'mime': mime,
                  'bytes': len(body) if body else 0, 'ok': code == 200 and bool(body)}
    except Exception as exc:
        output = {'asset': label, 'http_status': None, 'ok': False,
                  'error_type': type(exc).__name__}
        body = None
    results.append(output)
    return body if output['ok'] else None


class Command(BaseCommand):
    help = 'Check StyleJSON, vector source, Tehran PBF tile, sprite and glyph. Read-only.'

    def add_arguments(self, parser):
        parser.add_argument('--both', action='store_true', help='Probe both direct and proxy routes.')

    def handle(self, *args, **options):
        active = map_connection_mode()
        modes = ['proxy', 'direct'] if options['both'] and map_proxy_url() else [active]
        report = {'version': 'v41', 'selected_mode': active,
                  'proxy_configured': bool(map_proxy_url()), 'checks': {}}
        for mode in modes:
            items = []
            style_bytes = probe(mode, 'styles/liberty', 'style', items)
            style = {}
            if style_bytes:
                try:
                    style = json.loads(style_bytes)
                    if style.get('version') != 8 or not isinstance(style.get('layers'), list):
                        raise ValueError('incomplete style')
                except (ValueError, TypeError):
                    items[-1]['ok'] = False
                    items[-1]['problem'] = 'invalid_style_json'
                    style = {}
            sources = style.get('sources') or {}
            vector_path = next((provider_path(s.get('url')) for s in sources.values()
                                if isinstance(s, dict) and s.get('type') == 'vector' and
                                provider_path(s.get('url'))), None)
            if vector_path:
                tilejson_bytes = probe(mode, vector_path, 'tilejson', items)
                tilejson = {}
                if tilejson_bytes:
                    try:
                        tilejson = json.loads(tilejson_bytes)
                    except (ValueError, TypeError):
                        items[-1]['ok'] = False
                        items[-1]['problem'] = 'invalid_tilejson'
                templates = tilejson.get('tiles') or []
                if templates and isinstance(templates[0], str):
                    tile_url = tehran_tile_path(templates[0])
                    tile_path = provider_path(tile_url)
                    if tile_path:
                        probe(mode, tile_path, 'tehran_vector_tile', items)
                    else:
                        items.append({'asset': 'tehran_vector_tile', 'ok': False,
                                      'problem': 'tile_url_not_allowed'})
                else:
                    items.append({'asset': 'tehran_vector_tile', 'ok': False,
                                  'problem': 'missing_tile_template'})
            else:
                items.append({'asset': 'tilejson', 'ok': False,
                              'problem': 'no_allowed_vector_source'})
            sprite_path = provider_path(style.get('sprite'))
            if sprite_path:
                probe(mode, sprite_path + '.json', 'sprite_index', items)
            else:
                items.append({'asset': 'sprite_index', 'ok': False,
                              'problem': 'sprite_url_not_allowed'})
            glyph_template = style.get('glyphs')
            glyph_path = provider_path(glyph_template) if glyph_template else None
            if glyph_path:
                glyph_path = glyph_path.replace('{fontstack}', 'Noto%20Sans%20Regular').replace('{range}', '0-255')
                probe(mode, glyph_path, 'font_glyphs', items)
            else:
                items.append({'asset': 'font_glyphs', 'ok': False,
                              'problem': 'glyph_url_not_allowed'})
            # Sample raster source may be used at lower zoom and should be allowed.
            raster_path = next((provider_path((s.get('tiles') or [None])[0])
                                for s in sources.values() if isinstance(s, dict) and
                                s.get('type') == 'raster' and s.get('tiles') and
                                provider_path((s.get('tiles') or [None])[0])), None)
            if raster_path:
                probe(mode, tehran_tile_path(raster_path, zoom=4), 'low_zoom_raster', items)
            report['checks'][mode] = items
        checks = report['checks'].get(active, [])
        report['all_required_passed'] = bool(checks) and all(
            x['ok'] for x in checks if x['asset'] in
            ('style', 'tilejson', 'tehran_vector_tile', 'sprite_index', 'font_glyphs'))
        report['note'] = 'Browser MapLibre library, WebGL and session cookies still require browser-side checks.'
        self.stdout.write(json.dumps(report, ensure_ascii=False))
        if not report['all_required_passed']:
            self.stdout.write('MAP_ASSETS_INCOMPLETE: See failed asset labels and HTTP status above.')
        else:
            self.stdout.write('MAP_ASSETS_OK: If still grey, inspect browser UI diagnostics (CDN, WebGL, worker, cookies).')
