"""Explicit, fail-closed private import of cumulative GPT-6 proposals on Jobiew production.

Import never changes source rights, human decisions, company publication or public
feature flags. This command can only write six-axis UNREVIEWED proposals which
match independently existing DB source IDs/content/quotes. Each batch is
idempotent and re-import preserves verified human decisions.
"""
import os
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
    if (settings.DEBUG or
            os.environ.get('JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED', '0') != '1' or
            os.environ.get('JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED', '0') != '1' or
            os.environ.get('JOBIEW_CHECKPOINT_STAGING_ENABLED', '0') != '0' or
            os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0' or
            os.environ.get('JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED', '0') != '0' or
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

    def guard_database(self, expected_db):
        return guard_private_production(expected_db)
