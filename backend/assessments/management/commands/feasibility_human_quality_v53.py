"""Aggregate historical staff review events without changing scores or calling AI."""
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS
from assessments.review_workspace_v53 import build_metrics


def _write_csv(path, columns, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


class Command(BaseCommand):
    help = 'Read-only feasibility human review summary. Never publishes AI scores or calls providers.'

    def add_arguments(self, parser):
        parser.add_argument('--out', required=True, help='New directory; existing reports are never overwritten.')

    def handle(self, *args, **options):
        out = Path(options['out']).resolve()
        if out.exists():
            raise CommandError('Output directory exists; choose a new directory to preserve the previous report.')
        # Same scope as staff UI: work experiences only.
        assessments = list(AiAssessment.objects.filter(experience__source_kind='work').select_related(
            'experience').prefetch_related('dimensions__human_review_events').order_by('pk'))
        rows, totals = build_metrics(assessments)
        errors = Counter()
        private_events = []
        for a in assessments:
            for dim in a.dimensions.all():
                event = next(iter(dim.human_review_events.all()), None)
                if event is None:
                    continue
                if event.verdict in {'unsupported', 'missed_evidence'}:
                    errors[(dim.key, event.primary_error)] += 1
                private_events.append({
                    'assessment_id': a.pk, 'experience_id': a.experience_id,
                    'dimension_id': dim.pk, 'dimension_key': dim.key,
                    'model_score': dim.score if dim.score is not None else '',
                    'model_confidence': dim.confidence,
                    'verdict': event.verdict, 'primary_error': event.primary_error,
                    'note': event.note, 'reviewer_id': event.reviewer_id,
                    'review_event_id': event.pk, 'created_at': event.created_at.isoformat(),
                })
        out.mkdir(parents=True, exist_ok=False)
        _write_csv(out/'dimension_quality.csv', [
            'key','label','reviewed','decisive','supported','correct_abstention','unsupported',
            'missed_evidence','uncertain','error_count','observed_error_pct'], rows)
        _write_csv(out/'error_taxonomy.csv', ['dimension', 'primary_error', 'count'], [
            {'dimension': key, 'primary_error': cause, 'count': count}
            for (key,cause),count in sorted(errors.items())])
        private_path = out/'human_review_latest_PRIVATE.csv'
        _write_csv(private_path, ['assessment_id','experience_id','dimension_id','dimension_key',
            'model_score','model_confidence','verdict','primary_error','note','reviewer_id',
            'review_event_id','created_at'], private_events)
        try:
            private_path.chmod(0o600)
        except OSError:
            pass
        manifest = {
            'version': 'v53_feasibility_human_review',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'status': 'HUMAN_REVIEW_SAMPLE_NOT_PUBLICATION_APPROVAL',
            'assessments_in_scope': totals['assessments'],
            'dimension_rows_in_scope': totals['dimensions'],
            'reviewed_latest': totals['reviewed'],
            'unreviewed': totals['unreviewed'],
            'error_count': sum(errors.values()),
            'assessments_source_kind': 'work_only',
            'database_writes': 0,
            'external_api_requests': 0,
            'interpretation': 'Observed fractions depend on this small, non-random sample; uncertain reviews excluded from decisive denominator.',
            'does_not_approve_ai_publication': True,
            'no_public_source_or_company_ratings_generated': True,
            'deliverables': ['manifest.json', 'dimension_quality.csv', 'error_taxonomy.csv',
                             'human_review_latest_PRIVATE.csv'],
        }
        (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        self.stdout.write(json.dumps({k:manifest[k] for k in (
            'status','assessments_in_scope','dimension_rows_in_scope','reviewed_latest',
            'unreviewed','error_count','database_writes','external_api_requests')}, ensure_ascii=False))
