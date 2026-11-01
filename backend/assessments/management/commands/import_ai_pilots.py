"""Import historical Claude JSONL locally; NEVER approve or publish its scores.

Source hashes must match current imported experience content if provided, so a
response to an older crawler revision cannot silently attach to a newer review.
"""
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from assessments.models import AiAssessment, AiDimension, LEGACY_DIMENSIONS, LEGACY_CRITERIA_VERSION
from experiences.models import PublicExperience

KNOWN = {key for key, _ in LEGACY_DIMENSIONS}


class Command(BaseCommand):
    help = 'Offline import of historical AI results; source-hash checked, unpublished, repeatable.'

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='+')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        counts = dict(seen=0, imported=0, existing=0, unmatched=0,
                      invalid=0, source_hash_mismatch=0, dimension_rows=0)
        for filename in opts['files']:
            path = Path(filename)
            if not path.is_file():
                raise CommandError(f'AI input not found: {path}')
            with path.open(encoding='utf-8-sig') as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    counts['seen'] += 1
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        counts['invalid'] += 1
                        continue
                    if not isinstance(row, dict) or not isinstance(row.get('source_url'), str):
                        counts['invalid'] += 1
                        continue
                    result = row.get('result')
                    if not isinstance(result, dict) or not isinstance(result.get('dimensions'), dict):
                        counts['invalid'] += 1
                        continue
                    experience = PublicExperience.objects.filter(
                        source_url=row['source_url'], source_kind='work'
                    ).first()
                    if experience is None:
                        counts['unmatched'] += 1
                        continue
                    source_hash = row.get('source_content_sha256')
                    if source_hash and str(source_hash).lower() != experience.content_sha256.lower():
                        counts['source_hash_mismatch'] += 1
                        continue
                    dims = result['dimensions']
                    # Identity intentionally stays compatible with the v0.28 importer.
                    run_id = 'a' + hashlib.sha256((
                        str(row['source_url']) + '|' +
                        str(row.get('prompt_sha256') or row.get('prompt_version')) + '|' +
                        str(row.get('timestamp_utc')) + '|' + str(row.get('model'))
                    ).encode()).hexdigest()[:48]
                    if AiAssessment.objects.filter(experience=experience, run_id=run_id).exists():
                        counts['existing'] += 1
                        continue
                    if opts['dry_run']:
                        counts['imported'] += 1  # would import
                        counts['dimension_rows'] += sum(
                            key in KNOWN and isinstance(value, dict) for key, value in dims.items()
                        )
                        continue
                    with transaction.atomic():
                        assessment, created = AiAssessment.objects.get_or_create(
                            experience=experience, run_id=run_id,
                            defaults=dict(
                                criteria_version=LEGACY_CRITERIA_VERSION,
                                model_name=str(row.get('model') or 'unknown')[:120],
                                prompt_version=str(row.get('prompt_version') or row.get('pilot_version') or 'unknown')[:120],
                                raw_payload=row,
                                parse_status=str(row.get('status') or 'unreviewed')[:30],
                                independent_review_status='unreviewed',
                                publish_approved=False,
                            ),
                        )
                        if not created:
                            counts['existing'] += 1
                            continue
                        counts['imported'] += 1
                        for key, value in dims.items():
                            if key not in KNOWN or not isinstance(value, dict):
                                continue
                            score, conf = value.get('score'), value.get('confidence')
                            if score is not None and (type(score) is not int or not 1 <= score <= 10):
                                score = None
                            if type(conf) is not int or not 0 <= conf <= 100:
                                conf = 0
                            AiDimension.objects.create(
                                assessment=assessment, key=key, score=score, confidence=conf,
                                evidence=value.get('evidence') if isinstance(value.get('evidence'), list) else [],
                                explanation=str(value.get('explanation') or ''),
                                semantic_status='unreviewed',
                            )
                            counts['dimension_rows'] += 1
        self.stdout.write(json.dumps({'status': 'ok', 'dry_run': opts['dry_run'], **counts}, ensure_ascii=False))
