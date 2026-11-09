"""Private Windows-only staging: default read-only dry-run, explicit opt-in writes.

Writes local, source-locked *unapproved proposals*; it cannot issue classification
confirmations, copyright clearances, human score approvals or public ratings.
"""
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from criteria_v2.engine_v207 import story_from_experience
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore
from criteria_v2.pilot_import_v212 import (ENGINE, PilotImportError,
    aggregate_report, deterministic_run_id, load_from_files)
from criteria_v2.registry import version_for
from experiences.models import PublicExperience


def _source_matches(exp, case):
    if exp is None or exp.source_kind != case['kind']:
        return False
    if exp.copyright_review == 'blocked' or exp.company_attribution_status == 'rejected' or exp.independence_status == 'duplicate':
        return False
    if not exp.content_sha256 or len(exp.content_sha256) != 64:
        return False
    return story_from_experience(exp) == case['story']


def _stage_cases(cases, *, apply=False):
    """Validation and atomic writes; callable by isolated Django tests."""
    source_ids = [c['experience_id'] for c in cases]
    original = PublicExperience.objects.in_bulk(source_ids)
    if len(original) != len(cases) or any(not _source_matches(original.get(c['experience_id']),c) for c in cases):
        raise PilotImportError('Source mismatch, blocked/rejected/duplicate or source changed; no writes')
    ids = [deterministic_run_id(c, original[c['experience_id']].content_sha256) for c in cases]
    existing = set(CriteriaAnalysis.objects.filter(run_id__in=ids).values_list('run_id',flat=True))
    if not apply:
        return {'existing':len(existing),'would_insert':len(cases)-len(existing),'inserted':0}
    inserted = 0
    with transaction.atomic():
        locked = PublicExperience.objects.select_for_update().in_bulk(source_ids)
        if len(locked) != len(cases) or any(not _source_matches(locked.get(c['experience_id']),c) for c in cases):
            raise PilotImportError('Source changed during staging; entire transaction rolled back')
        # Fail closed: never silently overwrite a different run with same identifier.
        for case, run_id in zip(cases, ids):
            if CriteriaAnalysis.objects.filter(run_id=run_id).exists():
                continue
            exp = locked[case['experience_id']]
            analysis = CriteriaAnalysis.objects.create(
                experience=exp, criteria_version=version_for(case['kind']),
                source_content_sha256=exp.content_sha256,
                model_name='gpt-6-assistant-private-pilot',
                prompt_version='jobiew_assistant_annotation_v212',
                run_id=run_id, review_status='pilot_unverified',
                raw_payload={'engine':ENGINE, 'story_sha256':case['story_sha256'],
                             'prediction_sha256':case['prediction_sha256'],
                             'case_id':case['case_id'],
                             'detected_kind':case['detected_kind'],
                             'kind_confidence':case['kind_confidence'],
                             'human_reference':'NOT_INDEPENDENT',
                             'publication':'DISABLED'},
            )
            for key, value in case['dimensions'].items():
                CriteriaAxisScore.objects.create(
                    analysis=analysis, key=key, score=value['score'],
                    confidence=value['confidence'], evidence=value['evidence'],
                    explanation=value['explanation'], semantic_status='unreviewed')
            inserted += 1
    return {'existing':len(existing),'would_insert':len(cases)-len(existing),'inserted':inserted}


class Command(BaseCommand):
    help='Guarded private 6+6 pilot staging; default dry-run. Never approves or publishes.'

    def add_arguments(self, parser):
        parser.add_argument('--stories', required=True)
        parser.add_argument('--mapping', required=True)
        parser.add_argument('--predictions', required=True)
        parser.add_argument('--expected-db', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--acknowledge-unapproved-private-pilot', action='store_true')

    def handle(self, *args, **opts):
        # Even dry-run must be developer-local; never read private pilot against production.
        if os.name != 'nt' or not settings.DEBUG:
            raise CommandError('Command permitted only in Windows development environment')
        db = connection.settings_dict
        name, host = str(db.get('NAME','')), str(db.get('HOST') or '').lower()
        if (db.get('ENGINE') != 'django.db.backends.postgresql' or
            host not in ('','127.0.0.1','localhost','::1') or
            name != opts['expected_db'] or not name.endswith('_dev')):
            raise CommandError('Only explicitly named local PostgreSQL development database is permitted')
        if os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0':
            raise CommandError('Disable dual-six publication before private staging')
        if opts['apply'] and not opts['acknowledge_unapproved_private_pilot']:
            raise CommandError('Explicit --acknowledge-unapproved-private-pilot required for writes')
        repo = Path(settings.BASE_DIR).resolve().parent
        private_paths = [Path(opts[key]).expanduser().resolve() for key in ('stories','mapping','predictions')]
        if any(p == repo or repo in p.parents for p in private_paths):
            raise CommandError('Private JSON files must be outside the Git repository')
        try:
            cases = load_from_files(*private_paths)
            change = _stage_cases(cases, apply=opts['apply'])
            result = aggregate_report(cases)
            result.update(change)
        except PilotImportError as exc:
            raise CommandError(str(exc)) from None
        result['mode'] = 'STAGED_PRIVATE_PROPOSALS' if opts['apply'] else 'DRY_RUN_READ_ONLY'
        self.stdout.write(json.dumps(result,ensure_ascii=False,sort_keys=True))
        self.stdout.write('PAID_AI_CALLS: ZERO')
        self.stdout.write('HUMAN_APPROVAL: NONE')
        self.stdout.write('PUBLICATION: DISABLED')
