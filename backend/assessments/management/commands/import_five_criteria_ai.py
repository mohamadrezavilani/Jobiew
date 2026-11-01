"""Import reviewed-offline five-criterion AI research JSONL; never publish.

Dry-run is read-only. Strict hash matching avoids attaching scores to revised source
text. All writes for each record are atomic and idempotent, history is preserved.
"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from assessments.five_criteria_contract import validate_annotations, InvalidFiveCriteria
from assessments.models import AiAssessment, AiDimension, FIVE_CRITERIA_VERSION
from experiences.models import PublicExperience


class Command(BaseCommand):
    help = 'Import five-criterion AI research rows as unreviewed/unpublished; no external API calls.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--dataset-id', default='offline-75-v4-qa')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f'File does not exist: {path}')
        dataset_id = options['dataset_id']
        if not isinstance(dataset_id, str) or not 1 <= len(dataset_id) <= 80:
            raise CommandError('--dataset-id must be 1..80 characters')
        counts = dict(seen=0, imported=0, existing=0, invalid=0, unmatched=0,
                      source_hash_mismatch=0, ineligible=0, dimensions=0)
        with path.open(encoding='utf-8-sig') as source:
            for line in source:
                if not line.strip():
                    continue
                counts['seen'] += 1
                try:
                    row = json.loads(line)
                    dims = validate_annotations(row)
                except (ValueError, TypeError, InvalidFiveCriteria):
                    counts['invalid'] += 1
                    continue
                url = row.get('source_url')
                digest = row.get('source_content_sha256')
                if not isinstance(url, str) or not url or not isinstance(digest, str) or len(digest) != 64:
                    counts['invalid'] += 1
                    continue
                experience = PublicExperience.objects.filter(source_url=url, source_kind='work').first()
                if experience is None:
                    counts['unmatched'] += 1
                    continue
                if experience.content_sha256.lower() != digest.lower():
                    counts['source_hash_mismatch'] += 1
                    continue
                if experience.company_attribution_status == 'rejected' or experience.independence_status == 'duplicate':
                    counts['ineligible'] += 1
                    continue
                # Duplicate author/source records never become independent samples. Full
                # eligibility is deliberately NOT asserted by this importer.
                stable = f'{FIVE_CRITERIA_VERSION}|{dataset_id}|{url}|{digest}'
                run_id = 'f' + hashlib.sha256(stable.encode('utf-8')).hexdigest()[:48]
                if AiAssessment.objects.filter(experience=experience, run_id=run_id).exists():
                    counts['existing'] += 1
                    continue
                if options['dry_run']:
                    counts['imported'] += 1
                    counts['dimensions'] += len(dims)
                    continue
                with transaction.atomic():
                    assessment, created = AiAssessment.objects.get_or_create(
                        experience=experience, run_id=run_id,
                        defaults={
                            'criteria_version': FIVE_CRITERIA_VERSION,
                            'model_name': 'ChatGPT-offline-qualitative',
                            'prompt_version': dataset_id,
                            'raw_payload': row,
                            'parse_status': 'imported_provisional',
                            'independent_review_status': 'unreviewed',
                            'publish_approved': False,
                        },
                    )
                    if not created:
                        counts['existing'] += 1
                        continue
                    for key, data in dims.items():
                        AiDimension.objects.create(
                            assessment=assessment, key=key,
                            score=data['score'], confidence=data['confidence'],
                            evidence=data['evidence'], explanation=data['explanation'],
                            semantic_status='unreviewed',
                        )
                    counts['imported'] += 1
                    counts['dimensions'] += len(dims)
        self.stdout.write(json.dumps({'status':'RESEARCH_ONLY_NOT_PUBLIC',
                       'dry_run':options['dry_run'], **counts}, ensure_ascii=False))
