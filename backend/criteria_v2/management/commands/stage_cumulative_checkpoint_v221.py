"""Stage cumulative checkpoint privately against existing local Windows dev DB.

Reads the ZIP as inert bytes; calls existing strict source identity and evidence
checks against the database. No production, rights approval or public scores.
"""
import json
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from criteria_v2.checkpoint_cumulative_v221 import validate_cumulative, CheckpointError
from criteria_v2.checkpoint_contract_v218 import select_batch, summary_only
from criteria_v2.management.commands.stage_dual6_checkpoint_v218 import (
    _guard_local_dev, check_candidate, stage_one,
)

class Command(BaseCommand):
    help = 'Read-only dry run or private local PostgreSQL import of cumulative GPT-6 checkpoint.'

    def add_arguments(self, parser):
        parser.add_argument('--checkpoint', required=True)
        parser.add_argument('--expected-db', required=True)
        parser.add_argument('--expected-checkpoint-sha256', required=True)
        parser.add_argument('--expected-source-sha256', required=True)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--acknowledge-unverified-private-data', action='store_true')

    def guard_database(self, expected_db):
        return _guard_local_dev(expected_db)

    def handle(self, *args, **opts):
        database = self.guard_database(opts['expected_db'])
        if opts['apply'] != opts['acknowledge_unverified_private_data']:
            raise CommandError('PRIVATE_APPLY_REQUIRES_EXPLICIT_ACKNOWLEDGEMENT')
        try:
            rows, ledger, qa = validate_cumulative(
                opts['checkpoint'],
                expected_checkpoint_sha256=opts['expected_checkpoint_sha256'],
                expected_source_sha256=opts['expected_source_sha256'],
            )
            selected, duplicates = select_batch(
                rows, ledger, after_id=opts['after_id'], limit=opts['limit'])
            # Preflight EVERY candidate before first write. A source hash,
            # quote or company mismatch aborts the batch with no modifications.
            states = [check_candidate(row)[3] for row in selected]
        except CheckpointError as exc:
            raise CommandError('CUMULATIVE_PREFLIGHT_FAILED: ' + str(exc)) from None
        except (ValueError, TypeError, KeyError, ValidationError, DatabaseError):
            raise CommandError('CUMULATIVE_PREFLIGHT_REJECTED_NO_PRIVATE_TEXT_LOGGED') from None
        report = summary_only(qa, selected=selected, duplicates=duplicates,
                              existing=states.count('existing'), would_insert=states.count('new'))
        report.update({
            'database': database,
            'checkpoint_sha256': qa['checkpoint_zip_sha256'],
            'source_archive_verified_here': False,
            'source_db_identity_and_evidence': 'PREFLIGHT_PASS',
            'mode': 'PRIVATE_STAGE_UNVERIFIED' if opts['apply'] else 'DRY_RUN_READ_ONLY',
            'inserted': 0, 'changes': 0,
            'last_candidate_id': selected[-1]['experience_id'] if selected else opts['after_id'],
        })
        if opts['apply']:
            for row in selected:
                try:
                    report['inserted'] += int(stage_one(row))
                except CheckpointError as exc:
                    raise CommandError('CUMULATIVE_STAGE_ABORTED_AT_ID_' + str(row['experience_id'])
                                       + ': ' + str(exc)
                                       + '; PREVIOUS_ROWS_COMMITTED=' + str(report['inserted'])) from None
                except (ValueError, TypeError, ValidationError, DatabaseError):
                    raise CommandError('CUMULATIVE_STAGE_DB_ERROR_AT_ID_'
                                       + str(row['experience_id']) + '; PREVIOUS_ROWS_COMMITTED='
                                       + str(report['inserted']) + '; PRIVATE_TEXT_NOT_LOGGED') from None
            report['changes'] = report['inserted']
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        self.stdout.write('NO_APPROVALS; NO_PUBLICATION; NO_AI_REQUESTS; REQUIRES_SEPARATE_RIGHTS_AND_SEMANTIC_REVIEW')