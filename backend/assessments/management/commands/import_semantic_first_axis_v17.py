"""Validate and stage AI-proposed changes to the first criterion; does not activate."""
import json
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from assessments.models import AiDimension, SemanticScoreOverride

FIRST_KEY='work_conditions_pressure'

class Command(BaseCommand):
    help='Stage v16 semantic suggestions as inactive revisions. No public impact.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--batch-id',required=True)
        parser.add_argument('--dry-run',action='store_true')

    def handle(self, *args, **opts):
        path=Path(opts['file'])
        batch=opts['batch_id'].strip()
        if not path.is_file():
            raise CommandError('JSONL file not found')
        if not 1 <= len(batch) <= 105 or not re.fullmatch(r'[A-Za-z0-9_.-]+', batch):
            raise CommandError('Batch ID must be 1..105 ASCII letters, digits, . _ -')
        lines=[]
        for number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if line.strip():
                try: lines.append((number,json.loads(line)))
                except ValueError as exc: raise CommandError(f'Line {number}: invalid JSON: {exc}') from exc
        counts={'seen':len(lines),'kept':0,'eligible':0,'existing':0,'to_import':0,'evidence_unmatched_advisory':0}
        unique=set(); prepared=[]
        # Validate entire input BEFORE starting any write.
        for lineno,row in lines:
            if not isinstance(row,dict):
                raise CommandError(f'Line {lineno}: expected object')
            if row.get('criterion')!=FIRST_KEY or row.get('rating_direction')!='10_IS_BETTER':
                raise CommandError(f'Line {lineno}: invalid first-axis criterion/direction')
            action=row.get('review_decision')
            if action not in ('keep','revise','abstain'):
                raise CommandError(f'Line {lineno}: invalid review_decision')
            try: dim_id=int(row['dimension_id']); assessment_id=int(row['assessment_id']); exp_id=int(row['experience_id'])
            except (ValueError,TypeError,KeyError) as exc: raise CommandError(f'Line {lineno}: missing/invalid IDs') from exc
            if dim_id in unique: raise CommandError(f'Line {lineno}: duplicated dimension')
            unique.add(dim_id)
            dim=AiDimension.objects.select_related('assessment__experience').filter(pk=dim_id).first()
            if dim is None: raise CommandError(f'Line {lineno}: dimension missing: {dim_id}')
            assessment=dim.assessment; exp=assessment.experience
            if (dim.key!=FIRST_KEY or assessment.criteria_version!='five_v1' or
                    assessment.pk!=assessment_id or exp.pk!=exp_id or
                    str(exp.company_id)!=str(row.get('company_id')) or exp.source_kind!='work' or
                    exp.source_url!=row.get('source_url')):
                raise CommandError(f'Line {lineno}: dimension/assessment/experience mismatch')
            sha=row.get('source_content_sha256')
            fingerprint=row.get('source_row_sha256')
            if any(not isinstance(d,str) or not re.fullmatch(r'[a-fA-F0-9]{64}',d) for d in (sha,fingerprint)):
                raise CommandError(f'Line {lineno}: SHA-256 format invalid')
            if exp.content_sha256.lower()!=sha.lower():
                raise CommandError(f'Line {lineno}: source hash mismatch')
            base=row.get('baseline_score'); proposed=row.get('proposed_score')
            if base!=dim.score:
                raise CommandError(f'Line {lineno}: baseline score changed')
            if action=='keep':
                if proposed!=base: raise CommandError(f'Line {lineno}: keep must preserve baseline')
                counts['kept']+=1
                continue
            if action=='revise' and (type(proposed) is not int or not 1<=proposed<=10):
                raise CommandError(f'Line {lineno}: revise score must be 1..10')
            if action=='abstain' and proposed is not None:
                raise CommandError(f'Line {lineno}: abstain requires null score')
            explanation=str(row.get('semantic_rationale_fa') or '').strip()
            if len(explanation)<12: raise CommandError(f'Line {lineno}: rationale too short')
            evidence=str(row.get('evidence_excerpt_exact') or '')
            if evidence and evidence not in (exp.title+'\n'+exp.body+'\n'+' '.join(map(str,exp.pros))+'\n'+' '.join(map(str,exp.cons))):
                counts['evidence_unmatched_advisory']+=1
            counts['eligible']+=1
            fingerprint_values=dict(action=action, baseline_score=base, proposed_score=proposed,
                                    source_content_sha256=sha.lower(), source_row_sha256=fingerprint.lower(),
                                    evidence_excerpt=evidence, rationale=explanation,
                                    review_method=str(row.get('review_method') or 'offline_AI_recommendation')[:100],
                                    status='proposed')
            existing=SemanticScoreOverride.objects.filter(dimension=dim,batch_id=batch).first()
            if existing:
                if any(getattr(existing,k)!=v for k,v in fingerprint_values.items()):
                    raise CommandError(f'Line {lineno}: conflicting existing revision')
                counts['existing']+=1
            else:
                prepared.append((dim,fingerprint_values))
        counts['to_import']=len(prepared)
        if not opts['dry_run']:
            with transaction.atomic():
                for dim,values in prepared:
                    SemanticScoreOverride.objects.create(dimension=dim,batch_id=batch,**values)
        self.stdout.write(json.dumps({'status':'RESEARCH_ONLY_NOT_PUBLIC','active':False,'dry_run':opts['dry_run'],
                                      'batch_id':batch,'imported':0 if opts['dry_run'] else len(prepared),**counts},ensure_ascii=False))
