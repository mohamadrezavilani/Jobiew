"""Final *technical* acceptance of private pilot integrity, without publication.

Must run only on Windows local dev PostgreSQL. Never reads or prints full stories
outside process memory, never calls a model, and never writes scores.
"""
import json
import os
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Count

from criteria_v2.pilot_dashboard_v213 import _only_pilot, _valid_analysis
from criteria_v2.engine_v207 import story_from_experience
from experiences.models import PublicExperience


class Command(BaseCommand):
    help='Read-only private pilot integrity and release blockers; no AI, no writes.'

    def add_arguments(self, parser):
        parser.add_argument('--expected-db', required=True)

    def handle(self,*args,**options):
        cfg=connection.settings_dict
        name=str(cfg.get('NAME') or '')
        host=str(cfg.get('HOST') or '').lower().strip()
        if (os.name != 'nt' or not settings.DEBUG or
            cfg.get('ENGINE') != 'django.db.backends.postgresql' or
            name != options['expected_db'] or not name.endswith('_dev') or
            host not in ('','localhost','127.0.0.1','::1') or
            os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED','0') != '0'):
            raise CommandError('Explicit local Windows development DB, DEBUG and disabled publication required')

        source=Counter()
        for kind, right, attribution, count in PublicExperience.objects.values_list(
                'source_kind','copyright_review','company_attribution_status').order_by().annotate(
                    n=Count('pk')):
            source['total']+=count
            if right != 'approved':source['copyright_not_approved']+=count
            if attribution != 'verified':source['attribution_not_verified']+=count
        pilot=Counter()
        for run in _only_pilot().select_related('experience').prefetch_related('axis_scores').iterator(chunk_size=200):
            pilot['analyses']+=1
            if _valid_analysis(run,story_from_experience(run.experience)):
                pilot['integrity_valid']+=1
                for item in run.axis_scores.all():
                    if item.score is None:pilot['abstentions']+=1
                    else:pilot['numeric']+=1
            else:
                pilot['integrity_invalid']+=1
        result={
            'database':name,
            'mode':'READ_ONLY_TECHNICAL_ACCEPTANCE',
            'source':dict(source), 'pilot':dict(pilot),
            'pilot_structural_pass': pilot['integrity_invalid']==0 and
                pilot['numeric']+pilot['abstentions']==pilot['integrity_valid']*6,
            'independent_quality_reference':'NOT_ESTABLISHED',
            'publication':'DISABLED', 'paid_ai_calls':0, 'database_writes':0,
            'overall_project_finished':False,
            'external_blocker':'SOURCE_RIGHTS_AND_INDEPENDENT_VALIDATION',
        }
        self.stdout.write(json.dumps(result,ensure_ascii=False,sort_keys=True))
        self.stdout.write('NO_WRITES; NO_AI; NO_PUBLICATION')
