"""Read-only CSV export of private AI-provisional company profiles (all work reviews)."""
import csv
from collections import defaultdict
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiDimension, FIVE_CRITERIA_VERSION
from assessments.five_criteria_contract import KEYS
from assessments.five_criteria_provisional_v11 import provisional_company_aggregate
from assessments.five_criteria_semantic_v17 import apply_active_semantic_overrides


class Command(BaseCommand):
    help='Export research-only 5-criterion company diagnostic means to CSV. No DB writes.'

    def add_arguments(self, parser):
        parser.add_argument('--output',required=True)
        parser.add_argument('--company-id',default=None)

    def handle(self,*args,**opts):
        target=Path(opts['output']).resolve()
        if target.suffix.lower()!='.csv':
            raise CommandError('Output must end with .csv')
        rows_qs=AiDimension.objects.filter(
            assessment__criteria_version=FIVE_CRITERIA_VERSION,
            assessment__experience__source_kind='work',key__in=KEYS,
        )
        if opts['company_id']:
            rows_qs=rows_qs.filter(assessment__experience__company_id=opts['company_id'])
        # Streaming reads, one SQL query for all companies; no N+1 aggregation.
        rows_qs=rows_qs.order_by('assessment__experience__company_id','assessment__experience_id','key','pk').values_list(
            'pk','assessment__experience__company_id','assessment__experience_id',
            'assessment__experience__content_sha256','key','score')
        target.parent.mkdir(parents=True,exist_ok=True)
        fields=('company_id','criterion','mean_provisional','n_provisional_used',
                'n_provisional_abstentions','n_ambiguous_run_rows','n_content_duplicates_excluded',
                'min_provisional','max_provisional','publication_status')
        from itertools import groupby
        company_count=0
        dimension_rows=0
        with target.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            for company_id,gr in groupby(rows_qs.iterator(chunk_size=2000),lambda r:r[1]):
                entries=[{'dimension_id':pk,'company_id':str(comp),'experience_id':str(exp),'content_hash':h,
                          'dimension':dim,'score':score} for pk,comp,exp,h,dim,score in gr]
                profile=provisional_company_aggregate(company_id,apply_active_semantic_overrides(entries))
                for key in KEYS:
                    m=profile['criteria'][key]
                    writer.writerow({'company_id':company_id,'criterion':key,
                        **{field:m[field] for field in fields if field in m},
                        'publication_status':'NOT_APPROVED_FOR_PUBLICATION'})
                    dimension_rows+=1
                company_count+=1
        self.stdout.write(f'EXPORTED_PRIVATE_RESEARCH company_count={company_count} criteria_rows={dimension_rows} db_writes=0 path={target}')
