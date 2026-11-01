"""Explicit opt-in to staff-only provisional replacement (never human sign-off)."""
import json
import re
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from assessments.models import SemanticScoreOverride

class Command(BaseCommand):
    help='Activate staged corrections only in staff research means; original data retained.'
    def add_arguments(self,parser):
        parser.add_argument('--batch-id',required=True)
        parser.add_argument('--confirm-provisional',action='store_true')
    def handle(self,*args,**opts):
        source=opts['batch_id'].strip()
        target=source+'.active'
        if len(target)>120 or not re.fullmatch(r'[A-Za-z0-9_.-]+',source):
            raise CommandError('Invalid batch ID')
        qs=list(SemanticScoreOverride.objects.filter(batch_id=source,status='proposed').select_related('dimension__assessment__experience').order_by('pk'))
        if not qs: raise CommandError('No staged proposals for this batch')
        staged=[]; existing_count=0
        for item in qs:
            dim=item.dimension; exp=dim.assessment.experience
            if (exp.content_sha256.lower()!=item.source_content_sha256.lower() or
                dim.score!=item.baseline_score or dim.key!='work_conditions_pressure' or
                dim.assessment.criteria_version!='five_v1' or exp.source_kind!='work'):
                raise CommandError(f'Stale or invalid evidence for dimension {dim.pk}; activation cancelled')
            prior=SemanticScoreOverride.objects.filter(dimension=dim,batch_id=target).first()
            if prior:
                if (prior.source_row_sha256!=item.source_row_sha256 or
                    prior.action!=item.action or prior.proposed_score!=item.proposed_score or
                    prior.status!='active_provisional'):
                    raise CommandError(f'Conflicting active revision for {dim.pk}')
                existing_count+=1
                continue
            staged.append(item)
        if opts['confirm_provisional']:
            with transaction.atomic():
                for item in staged:
                    SemanticScoreOverride.objects.create(dimension=item.dimension,batch_id=target,
                       action=item.action,baseline_score=item.baseline_score,proposed_score=item.proposed_score,
                       source_content_sha256=item.source_content_sha256,
                       source_row_sha256=item.source_row_sha256,
                       evidence_excerpt=item.evidence_excerpt,rationale=item.rationale,
                       review_method=item.review_method,status='active_provisional')
        self.stdout.write(json.dumps({'status':'RESEARCH_ONLY_NOT_PUBLIC','batch_id':source,
          'dry_run':not opts['confirm_provisional'],'existing_active':existing_count,
          'would_activate':len(staged),'activated':len(staged) if opts['confirm_provisional'] else 0,
          'human_verified':False,'publication_changed':False},ensure_ascii=False))
