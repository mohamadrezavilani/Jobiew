"""Export private company-level provisional insights as a single read-only CSV."""
import csv
from itertools import groupby
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiDimension, FIVE_CRITERIA_VERSION
from assessments.five_criteria_contract import KEYS
from assessments.five_criteria_company_v7 import LABELS
from assessments.five_criteria_provisional_v11 import provisional_company_aggregate
from assessments.five_criteria_semantic_v17 import apply_active_semantic_overrides
from assessments.five_criteria_analysis_v13 import analyze_provisional_criteria
from companies.models import Company


class Command(BaseCommand):
    help='Export staff-only five criteria diagnostics; no DB writes or official ranking.'

    def add_arguments(self,parser):
        parser.add_argument('--output',required=True)
        parser.add_argument('--company-id',default=None)

    def handle(self,*args,**opts):
        dest=Path(opts['output']).resolve()
        if dest.suffix.lower()!='.csv':
            raise CommandError('Output must be a .csv file')
        qs=AiDimension.objects.filter(assessment__criteria_version=FIVE_CRITERIA_VERSION,
            assessment__experience__source_kind='work',key__in=KEYS)
        if opts['company_id']:
            qs=qs.filter(assessment__experience__company_id=opts['company_id'])
        rows=qs.order_by('assessment__experience__company_id','assessment__experience_id','key','pk').values_list(
            'pk','assessment__experience__company_id','assessment__experience_id',
            'assessment__experience__content_sha256','key','score')
        fields=['company_id','company_name','unique_work_experiences','criteria_with_score','scored_observations',
                'relative_strengths','relative_weaknesses']
        for key in KEYS:
            fields.extend([key+'_mean',key+'_n'])
        fields.append('publication_status')
        dest.parent.mkdir(parents=True,exist_ok=True)
        names=dict(Company.objects.values_list('id','display_name'))
        exported=0
        with dest.open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields)
            writer.writeheader()
            for company_id,gr in groupby(rows.iterator(chunk_size=2000),lambda r:r[1]):
                source=[{'dimension_id':pk,'company_id':str(cid),'experience_id':str(eid),'content_hash':sha,
                         'dimension':key,'score':score} for pk,cid,eid,sha,key,score in gr]
                summary=provisional_company_aggregate(company_id,apply_active_semantic_overrides(source))
                criteria=[{'key':key,**summary['criteria'][key]} for key in KEYS]
                insight=analyze_provisional_criteria(criteria)
                record={'company_id':company_id,'company_name':names.get(company_id,''),
                        'unique_work_experiences':len({r['experience_id'] for r in source}),
                        'criteria_with_score':insight['available_count'],
                        'scored_observations':insight['total_scored_observations'],
                        'relative_strengths':'؛ '.join(insight['strengths']),
                        'relative_weaknesses':'؛ '.join(insight['weaknesses']),
                        'publication_status':'NOT_APPROVED_FOR_PUBLICATION'}
                for key in KEYS:
                    stat=summary['criteria'][key]
                    record[key+'_mean']=stat['mean_provisional'] if stat['mean_provisional'] is not None else ''
                    record[key+'_n']=stat['n_provisional_used']
                writer.writerow(record)
                exported+=1
        self.stdout.write(f'EXPORTED_PRIVATE_COMPANY_ANALYSIS companies={exported} database_writes=0 path={dest}')
