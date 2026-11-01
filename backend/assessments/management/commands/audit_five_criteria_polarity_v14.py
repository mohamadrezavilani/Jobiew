"""Read-only audit of the historical first dimension in PostgreSQL."""
import csv
import json
from collections import Counter
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiDimension, FIVE_CRITERIA_VERSION
from assessments.five_criteria_polarity_v14 import FIRST_KEY, FIRST_LABEL, audit_direction

class Command(BaseCommand):
    help = 'Read-only audit; NO score updates. Investigate possible polarity mistakes.'
    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
    def handle(self, *args, **opts):
        path=Path(opts['output'])
        if path.exists():
            raise CommandError('Refusing to overwrite an existing audit: '+str(path))
        if not path.parent.is_dir():
            raise CommandError('Create output directory first: '+str(path.parent))
        counters=Counter()
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer=csv.DictWriter(stream, fieldnames=[
                'assessment_id','dimension_id','company_id','experience_id','source_url',
                'criteria_version','run_id','criterion_key','criterion_label',
                'score','audit_result','evidence','evidence_origin','human_review_status'
            ])
            writer.writeheader()
            qs=AiDimension.objects.filter(
                assessment__criteria_version=FIVE_CRITERIA_VERSION,
                key=FIRST_KEY,
            ).select_related('assessment','assessment__experience').order_by('assessment_id','pk')
            for d in qs.iterator(chunk_size=500):
                a=d.assessment; e=a.experience
                ev=' | '.join(str(item.get('quote','')) if isinstance(item,dict) else str(item)
                    for item in (d.evidence or []))
                code=audit_direction(d.score,ev)
                counters[code]+=1
                writer.writerow({
                    'assessment_id':a.pk,'dimension_id':d.pk,
                    'company_id':e.company_id,'experience_id':e.pk,'source_url':e.source_url,
                    'criteria_version':a.criteria_version,'run_id':a.run_id,
                    'criterion_key':d.key,'criterion_label':FIRST_LABEL,
                    'score':d.score if d.score is not None else '',
                    'audit_result':code,'evidence':ev,
                    'evidence_origin':'source_tag' if 'برچسب' in ev else 'text_or_other',
                    'human_review_status':a.independent_review_status,
                })
        self.stdout.write(json.dumps({
            'status':'READ_ONLY_POLARITY_AUDIT','output':str(path),
            'rows':sum(counters.values()),'by_audit_result':dict(counters),
            'score_updates':0,'database_writes':0,
            'note':'Review flagged results; no blanket inversion or automatic score rewriting.'
        },ensure_ascii=False))
