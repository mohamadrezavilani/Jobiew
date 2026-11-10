"""Explicit, fail-closed private import of cumulative GPT-6 proposals on Jobiew production.

Import never changes source rights, human decisions, company publication or public
feature flags. This command can only write six-axis UNREVIEWED proposals which
match independently existing DB source IDs/content/quotes. Each batch is
idempotent and re-import preserves verified human decisions.
"""
import os
import json
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from criteria_v2.checkpoint_cumulative_v221 import validate_cumulative, CheckpointError
from criteria_v2.checkpoint_contract_v218 import summary_only
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import check_candidate, stage_one
from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection
from django.http.request import validate_host
from criteria_v2.management.commands.stage_cumulative_checkpoint_v221 import Command as CumulativeCommand


def guard_private_production(expected_db):
    cfg = connection.settings_dict
    name = str(cfg.get('NAME') or '')
    host = str(cfg.get('HOST') or '').strip().lower()
    public_host = os.environ.get('JOBIEW_CHECKPOINT_PUBLIC_HOST', '').strip().lower()
    public = os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0')
    gpt = os.environ.get('JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED', '0')
    release_only = os.environ.get('JOBIEW_COMPANY_RELEASE_ONLY_ENABLED', '0')
    # Future checkpoints may be privately staged while previously explicitly
    # released, rights-cleared scores remain online; no new draft gets released.
    gate_ok = ((public == '0' and gpt == '0') or
               (public == '1' and gpt == '1' and release_only == '1'))
    if (settings.DEBUG or not gate_ok or release_only != '1' or
            os.environ.get('JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED', '0') != '1' or
            os.environ.get('JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED', '0') != '1' or
            os.environ.get('JOBIEW_CHECKPOINT_STAGING_ENABLED', '0') != '0' or
            cfg.get('ENGINE') != 'django.db.backends.postgresql' or
            expected_db != 'jobiew' or name != 'jobiew' or
            host not in ('', 'localhost', '127.0.0.1', '::1') or
            not public_host or '/' in public_host or ':' in public_host or
            public_host not in settings.ALLOWED_HOSTS or
            not validate_host(public_host, settings.ALLOWED_HOSTS)):
        raise CommandError('PRIVATE_PRODUCTION_IMPORT_GUARD_REJECTED')
    return name


class Command(CumulativeCommand):
    help = ('Import only source-matched unverified GPT-6 drafts privately into '
            'Jobiew PostgreSQL; NEVER auto-approve or publish.')

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--all-batches', action='store_true')
        parser.add_argument('--max-total', type=int, default=3000)

    def guard_database(self, expected_db):
        return guard_private_production(expected_db)

    def handle(self, *args, **opts):
        if not opts['all_batches']:
            return super().handle(*args, **opts)
        db = self.guard_database(opts['expected_db'])
        if opts['apply'] != opts['acknowledge_unverified_private_data']:
            raise CommandError('PRIVATE_APPLY_REQUIRES_EXPLICIT_ACKNOWLEDGEMENT')
        if not 1 <= opts['max_total'] <= 10000:
            raise CommandError('INVALID_MAX_TOTAL_BOUND')
        try:
            rows, ledger, qa = validate_cumulative(
                opts['checkpoint'],
                expected_checkpoint_sha256=opts['expected_checkpoint_sha256'],
                expected_source_sha256=opts['expected_source_sha256'])
            selected = [row for row in rows if
                        row['experience_id'] > opts['after_id'] and
                        ledger[row['experience_id']].get('exact_duplicate_of_experience_id') is None]
            excluded = len(rows) - len(selected)
            if len(selected) > opts['max_total']:
                raise CommandError('MAX_TOTAL_EXCEEDED_USE_SMALLER_CURSORS')
            # Verify every source and every quote BEFORE the first write.
            states = []
            for row in selected:
                try:
                    states.append(check_candidate(row)[3])
                except (CheckpointError, ValueError, TypeError, ValidationError, DatabaseError):
                    raise CommandError(
                        'ALL_BATCHES_SOURCE_PREFLIGHT_FAILED_AT_ID_'
                        + str(row['experience_id']) + '_NO_WRITES') from None
        except CommandError:
            raise
        except CheckpointError as exc:
            raise CommandError('ALL_BATCHES_ARCHIVE_VALIDATION_FAILED: ' + str(exc)) from None
        except (ValueError, TypeError, ValidationError, DatabaseError):
            raise CommandError('ALL_BATCHES_VALIDATION_FAILED_NO_PRIVATE_TEXT_LOGGED') from None
        report = summary_only(qa, selected=selected, duplicates=excluded,
            existing=states.count('existing'), would_insert=states.count('new'))
        report.update({'database': db, 'mode': ('PRIVATE_STAGE_UNVERIFIED'
            if opts['apply'] else 'DRY_RUN_READ_ONLY'),
            'inserted': 0, 'last_candidate_id': (
                selected[-1]['experience_id'] if selected else opts['after_id']),
            'all_batches': True, 'changes': 0})
        if opts['apply']:
            for row in selected:
                try:
                    report['inserted'] += int(stage_one(row))
                except (CheckpointError, ValueError, TypeError, ValidationError, DatabaseError):
                    raise CommandError(
                        'PRIVATE_IMPORT_STOPPED_AT_ID_' + str(row['experience_id'])
                        + '_COMMITTED=' + str(report['inserted'])
                        + '_RETRY_SAFE_NO_PRIVATE_TEXT_LOGGED') from None
            report['changes'] = report['inserted']
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        self.stdout.write('NO_AUTOMATIC_APPROVALS_OR_PUBLICATION; SOURCE_RIGHTS_UNVERIFIED')

