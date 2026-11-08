"""Explicit private, read-only sample export on a developer's local machine.

Never logs raw source, updates DB, calls AI or creates files inside the repo.
"""
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from experiences.models import PublicExperience
from criteria_v2.engine_v207 import story_from_experience
from criteria_v2.pilot_v211 import select_cases, make_private_documents


class Command(BaseCommand):
    help = 'Create blind private human-label pilot from developer-local Django DB only; never publish.'

    def add_arguments(self, parser):
        parser.add_argument('--output-dir', required=True)
        parser.add_argument('--per-kind', type=int, default=20)
        parser.add_argument('--seed', default='20261108')
        parser.add_argument('--acknowledge-private-export', action='store_true')
        parser.add_argument('--include-pending-copyright', action='store_true')

    def handle(self, *args, **opts):
        if not opts['acknowledge_private_export']:
            raise CommandError('Explicit --acknowledge-private-export required')
        if os.name != 'nt':
            raise CommandError('Private pilot export is Windows-local only')
        if opts['per_kind'] not in range(1, 51):
            raise CommandError('--per-kind must be between 1 and 50')
        db = connection.settings_dict
        host = (db.get('HOST') or '').strip().lower()
        if host not in ('', 'localhost', '127.0.0.1', '::1'):
            raise CommandError('Refusing non-local PostgreSQL/database connection')
        if not any(x in db['ENGINE'] for x in ('postgresql', 'sqlite3')):
            raise CommandError('Unrecognized Django database engine')
        root = Path(settings.BASE_DIR).resolve().parent
        output = Path(opts['output_dir']).expanduser().resolve()
        if output == root or root in output.parents:
            raise CommandError('Private export directory must be OUTSIDE the Git repository')
        if output.exists():
            raise CommandError('Target directory already exists; will not overwrite private data')
        qs = (PublicExperience.objects.filter(source_kind__in=('work','interview'))
              .exclude(copyright_review='blocked')
              .exclude(company_attribution_status='rejected')
              .exclude(independence_status='duplicate').order_by('pk'))
        if not opts['include_pending_copyright']:
            qs = qs.filter(copyright_review='approved')
        candidates = []
        for exp in qs.iterator(chunk_size=500):
            story = story_from_experience(exp)
            if 50 <= len(story.strip()) <= 8000:
                candidates.append({'local_id':exp.pk,'kind':exp.source_kind,'story':story})
        chosen = select_cases(candidates, per_kind=opts['per_kind'], seed=opts['seed'])
        if not chosen:
            raise CommandError('No eligible local stories; do not loosen copyright policy without review')
        documents = make_private_documents(chosen)
        output.mkdir(parents=True, exist_ok=False)
        try:
            for name, data in zip(('stories.json','gold_template.json',
                                   'predictions_template.json','mapping_private.json'), documents):
                (output / name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        except Exception:
            # Preserve partially-created private files for manual review rather than
            # silently removing evidence; no external data transfers occur.
            raise CommandError('PRIVATE_EXPORT_IO_ERROR') from None
        counts = {kind:sum(x['kind']==kind for x in chosen) for kind in ('work','interview')}
        self.stdout.write('V211_PRIVATE_PILOT_EXPORT: PASS')
        self.stdout.write('CASE_COUNTS: '+json.dumps(counts))
        self.stdout.write('PRIVATE_SOURCE_TEXT: DO_NOT_COMMIT_OR_UPLOAD')
        self.stdout.write('PAID_AI_CALLS: ZERO')
