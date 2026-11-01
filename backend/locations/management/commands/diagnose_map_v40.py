"""Safe, read-mostly upstream map connectivity diagnostic for staff developers."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from locations.map_asset_proxy_v39 import fetch_asset, map_proxy_url, map_connection_mode


class Command(BaseCommand):
    help = 'Probe official OpenFreeMap style directly and via configured SOCKS5 proxy; never print secrets.'

    def add_arguments(self, parser):
        parser.add_argument('--select-working', action='store_true',
                            help='Save preferred connection mode ONLY if upstream HTTP 200 was verified.')

    def handle(self, *args, **options):
        configured = bool(map_proxy_url())
        results = {}
        for mode in (('proxy', 'direct') if configured else ('direct',)):
            try:
                code, data, mime = fetch_asset('styles/liberty', mode=mode)
                valid_style = bool(code == 200 and mime == 'application/json')
                if valid_style:
                    try:
                        style = json.loads(data)
                        valid_style = (isinstance(style, dict) and style.get('version') == 8)
                    except (ValueError, TypeError, UnicodeError):
                        valid_style = False
                results[mode] = {'http_status': int(code), 'style_ok': bool(valid_style)}
            except Exception as exc:
                # NEVER print str(exc): proxy clients may include credentials in exception URLs.
                results[mode] = {'http_status': None,
                                 'style_ok': False,
                                 'error_type': type(exc).__name__}
        result = {'selected_mode': map_connection_mode(),
                  'proxy_configured': configured,
                  'style_test': results,
                  'no_database_changes': True}
        self.stdout.write(json.dumps(result, ensure_ascii=False))
        if options['select_working']:
            selection = ('proxy' if results.get('proxy', {}).get('style_ok') else
                         'direct' if results.get('direct', {}).get('style_ok') else None)
            if not selection:
                raise CommandError('Neither route received an allowed style response. No changes made.')
            if selection != map_connection_mode():
                file = Path(settings.BASE_DIR) / 'data' / 'map_connection_mode.txt'
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(selection + '\n', encoding='ascii')
            self.stdout.write(f'WORKING_MAP_MODE={selection}')
            if not results.get(selection, {}).get('style_ok'):
                raise CommandError('No valid style loaded')
