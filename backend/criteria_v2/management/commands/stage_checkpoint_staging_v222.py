"""Strict opt-in private import into *separate* Linux PostgreSQL staging DB.

Shares v221's byte-for-byte archive and source/score validation. Does NOT
support applying unverified data to production DBs, even when run as root.
"""
import os
from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection
from django.http.request import validate_host
from criteria_v2.management.commands.stage_cumulative_checkpoint_v221 import Command as BaseCumulativeCommand


def guard_dedicated_staging(expected_db):
    cfg = connection.settings_dict
    name = str(cfg.get('NAME') or '')
    host = str(cfg.get('HOST') or '').strip().lower()
    stage_host = os.environ.get('JOBIEW_CHECKPOINT_STAGING_HOST', '').strip().lower()
    public_host = os.environ.get('JOBIEW_CHECKPOINT_PUBLIC_HOST', '').strip().lower()
    hosts = settings.ALLOWED_HOSTS
    if (settings.DEBUG or os.environ.get('JOBIEW_CHECKPOINT_IMPORT_STAGING_ENABLED') != '1' or
            os.environ.get('JOBIEW_CHECKPOINT_STAGING_ENABLED') != '1' or
            os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0' or
            os.environ.get('JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED', '0') != '0' or
            cfg.get('ENGINE') != 'django.db.backends.postgresql' or
            not isinstance(expected_db, str) or not expected_db.endswith('_staging') or
            name != expected_db or host not in ('localhost', '127.0.0.1', '::1', '') or
            not stage_host or not public_host or stage_host == public_host or
            '/' in stage_host or ':' in stage_host or '/' in public_host or ':' in public_host or
            stage_host not in hosts or validate_host(public_host, hosts)):
        raise CommandError('DEDICATED_NONPRODUCTION_HTTPS_STAGING_POSTGRESQL_REQUIRED')
    return name


class Command(BaseCumulativeCommand):
    help = 'Stage a cumulative checkpoint on a dedicated private nonproduction PostgreSQL staging DB only.'

    def guard_database(self, expected_db):
        return guard_dedicated_staging(expected_db)