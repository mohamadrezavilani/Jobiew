"""Opt-in Claude five-score comparison in Django Admin; no public views."""
import os
from urllib.parse import urlencode
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils.cache import patch_cache_control

from assessments.models import AiAssessment, DIMENSIONS, FIVE_CRITERIA_VERSION
from assessments.claude_validation_models_v111 import ClaudeValidationRun
from assessments.claude_validation_v111 import validate_one, _pilot_limit, _model_id


def _permissions(request,run=False):
    required=['assessments.view_aiassessment', 'assessments.view_aidimension',
              'experiences.view_publicexperience']
    if run:required.append('assessments.change_aiassessment')
    if not (request.user.is_active and request.user.is_staff and all(request.user.has_perm(p) for p in required)):
        raise PermissionDenied


def _context(admin_view,request,title):
    return {**admin_view.admin_site.each_context(request),'title':title,
            'opts':admin_view.model._meta,'has_view_permission':True}


def _render(request,name,context):
    response=TemplateResponse(request,name,context)
    patch_cache_control(response,private=True,no_store=True)
    return response


def dashboard(admin_view,request):
    _permissions(request)
    if request.method!='GET':return HttpResponseNotAllowed(['GET'])
    q=(request.GET.get('q') or '').strip()[:120]
    qs=(AiAssessment.objects.filter(criteria_version=FIVE_CRITERIA_VERSION,
                experience__source_kind='work').select_related('experience','experience__company')
                .order_by('-pk'))
    if q:
        clause=(Q(experience__company__display_name__icontains=q)|
                Q(experience__job_title__icontains=q))
        if q.isdigit():clause |= Q(pk=int(q))
        qs=qs.filter(clause)
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    ids=[a.pk for a in page.object_list]
    runs=ClaudeValidationRun.objects.filter(assessment_id__in=ids).order_by('-pk')
    last={}
    for r in runs:
        if r.assessment_id not in last:last[r.assessment_id]=r
    items=[{'assessment':a,'last':last.get(a.pk)} for a in page.object_list]
    history=(ClaudeValidationRun.objects.select_related('assessment','assessment__experience',
                'assessment__experience__company').order_by('-pk')[:12])
    history_rows=[]
    for run in history:
        comparison=run.comparison if isinstance(run.comparison,dict) else {}
        history_rows.append({'run':run,
            'changed':sum(v.get('original')!=v.get('claude') for v in comparison.values()),
            'attention':sum(bool(v.get('needs_attention')) for v in comparison.values())})
    limit=_pilot_limit()
    ctx=_context(admin_view,request,'صحت‌سنجی مستقل Claude')
    ctx.update({'items':items,'page':page,'q':q,'page_query':urlencode({'q':q})+'&',
                'history_rows':history_rows,'limit':limit,'used':ClaudeValidationRun.objects.count(),
                'remaining':max(0,limit-ClaudeValidationRun.objects.count()),
                'can_run':False,  # dual6_v202: old paid scoring frozen
                'key_ready':bool(os.environ.get('ANTHROPIC_API_KEY','').strip()),
                'model_id':_model_id(), 'fields':DIMENSIONS})
    return _render(request,'admin/assessments/aiassessment/claude_dashboard_v111.html',ctx)


def detail(admin_view,request,assessment_id):
    _permissions(request)
    if request.method!='GET':return HttpResponseNotAllowed(['GET'])
    a=get_object_or_404(AiAssessment.objects.select_related('experience','experience__company'),
          pk=assessment_id,criteria_version=FIVE_CRITERIA_VERSION,experience__source_kind='work')
    runs=list(ClaudeValidationRun.objects.filter(assessment=a).order_by('-pk')[:10])
    last=next((r for r in runs if r.status=='completed'),None)
    dims={d.key:d for d in a.dimensions.all()}
    rows=[]
    for key,label in DIMENSIONS:
        d=dims.get(key)
        compared=(last.comparison if last else {}).get(key) or {}
        rows.append({'key':key,'label':label,'original':d,'comparison':compared})
    ctx=_context(admin_view,request,f'مقایسه Claude با AI #{a.pk}')
    ctx.update({'assessment':a,'experience':a.experience,'rows':rows,
                'history':runs,'last':last,'model_id':_model_id(),
                'remaining':max(0,_pilot_limit()-ClaudeValidationRun.objects.count()),
                'can_run':False,  # dual6_v202: old paid scoring frozen
                'key_ready':bool(os.environ.get('ANTHROPIC_API_KEY','').strip())})
    return _render(request,'admin/assessments/aiassessment/claude_detail_v111.html',ctx)


def run(admin_view,request,assessment_id):
    _permissions(request,run=True)
    if request.method!='POST':return HttpResponseNotAllowed(['POST'])
    # Old five-axis paid analysis is frozen until a versioned replacement is approved.
    return JsonResponse({'ok':False,'error':'legacy_scoring_suspended',
                         'message':'اجرای جدید تحلیل پنج‌معیاری غیرفعال است.'}, status=409)  # dual6_v202
    get_object_or_404(AiAssessment,pk=assessment_id)
    try:
        new,called=validate_one(assessment_id,request.user,
                                force=request.POST.get('force')=='true')
        result={'ok':new.status=='completed','status':new.status,'called':called,
                'run_id':new.pk,'error':new.error_type if new.status=='failed' else '',
                'detail_url':f'/admin/assessments/aiassessment/claude/{assessment_id}/'}
        if new.status=='failed':result['message']='درخواست Claude ناموفق بود؛ هزینه یا علت در کنسول Anthropic بررسی شود.'
        return JsonResponse(result,status=200 if new.status=='completed' else 502)
    except (ValueError, PermissionError) as exc:
        return JsonResponse({'ok':False,'message':str(exc)},status=400)
