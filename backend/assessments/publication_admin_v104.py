"""Staff-only workflow: source checks, five human judgments, final publish/revoke."""
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Prefetch
from django.http import HttpResponseRedirect, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control

from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS, FIVE_CRITERIA_VERSION
from assessments.publication_workflow_v104 import publication_blockers, latest_verdict, source_url, set_publication
from assessments.publication_simple_v105 import preliminary_blockers, quick_decision, save_dimension_decisions
from experiences.models import ExperienceReviewEvent


def _permission(request):
    if not (request.user.has_perm('assessments.view_aiassessment') and
            request.user.has_perm('assessments.view_aidimension') and
            request.user.has_perm('experiences.view_publicexperience')):
        raise PermissionDenied


def _context(admin_view, request, title):
    return {**admin_view.admin_site.each_context(request), 'title':title,
            'opts':admin_view.model._meta,'has_view_permission':True}


def _respond(request, template, ctx):
    response=TemplateResponse(request, template, ctx)
    patch_cache_control(response,private=True,no_store=True)
    return response


def publication_queue(admin_view, request):
    if request.method != 'GET': return HttpResponseNotAllowed(['GET'])
    _permission(request)
    q=(request.GET.get('q') or '').strip()[:120]
    state=request.GET.get('state','all')
    qs=(AiAssessment.objects.filter(criteria_version=FIVE_CRITERIA_VERSION)
         .select_related('experience','experience__company').order_by('-created_at','-pk'))
    if q:
        qs=qs.filter(Q(experience__company__display_name__icontains=q)|
                     Q(experience__title__icontains=q)|Q(experience__source_url__icontains=q))
    if state=='pending':qs=qs.filter(publish_approved=False)
    elif state=='published':qs=qs.filter(publish_approved=True)
    else:state='all'
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    ctx=_context(admin_view,request,'صف بررسی و انتشار نتایج AI')
    ctx.update({'page_obj':page,'q':q,'state':state,'page_query':urlencode({'q':q,'state':state})+'&',
                'can_publish':request.user.has_perm('assessments.change_aiassessment')})
    return _respond(request,'admin/assessments/aiassessment/publication_queue_v104.html',ctx)


def publication_detail(admin_view,request,assessment_id):
    _permission(request)
    a=get_object_or_404(AiAssessment.objects.select_related('experience','experience__company'),
                        pk=assessment_id,criteria_version=FIVE_CRITERIA_VERSION)
    exp=a.experience
    can_review=request.user.has_perm('assessments.add_aihumanreviewevent')
    can_source=request.user.has_perm('experiences.add_experiencereviewevent')
    can_publish=request.user.has_perm('assessments.change_aiassessment')
    if request.method=='POST':
        action=request.POST.get('action')
        if action in {'review_dimensions', 'publish_reviewed'}:
            if not (can_publish and can_review): raise PermissionDenied
            try:
                decisions = {key: request.POST.get('decision_' + key, '') for key, _ in DIMENSIONS}
                updated = save_dimension_decisions(request, a.pk, decisions)
                if action == 'publish_reviewed':
                    if not all(x == 'yes' for x in decisions.values()):
                        messages.warning(request, 'تصمیم‌ها ذخیره شدند؛ برای انتشار، تأیید همهٔ پنج شاخص لازم است.')
                    else:
                        quick_decision(request, a.pk, approve=True)
                        messages.success(request, 'پنج شاخص تأیید شدند و ارزیابی AI منتشر شد.')
                else:
                    messages.success(request, f'بررسی هر پنج شاخص ذخیره شد ({updated} تصمیم جدید).')
            except (ValidationError, ValueError) as exc:
                messages.error(request, 'بررسی یا انتشار انجام نشد: ' + str(exc))
        elif action == 'quick_reject':
            if not can_publish: raise PermissionDenied
            try:
                quick_decision(request, a.pk, approve=False)
                messages.success(request, 'ارزیابی رد شد و انتشار آن غیرفعال است.')
            except (ValidationError, ValueError) as exc:
                messages.error(request, 'امکان ثبت تصمیم وجود ندارد: '+str(exc))
        elif action=='reviews':
            if not can_review or a.publish_approved: raise PermissionDenied
            if request.POST.get('acknowledged_source')!='on':
                messages.error(request,'ابتدا تأیید کنید متن اصلی را بررسی کرده‌اید.')
            else:
                try:
                    drafts=[]
                    for d in a.dimensions.order_by('pk'):
                        value=request.POST.get(f'verdict_{d.key}','')
                        if not value:continue
                        errors=request.POST.get(f'error_{d.key}','')
                        note=request.POST.get(f'note_{d.key}','')
                        obj=AiHumanReviewEvent(dimension=d,reviewer=request.user,verdict=value,
                                               primary_error=errors,note=note)
                        obj.full_clean()
                        if latest_verdict(d) and latest_verdict(d).verdict==value and \
                           latest_verdict(d).primary_error==errors and latest_verdict(d).note==note:
                            continue
                        drafts.append(obj)
                    if not drafts:
                        messages.warning(request,'تصمیم تازه‌ای انتخاب نشده است.')
                    else:
                        with transaction.atomic():
                            for obj in drafts:obj.save()
                        messages.success(request,f'{len(drafts)} تصمیم انسانی ثبت شد. انتشار هنوز انجام نشده است.')
                except (ValidationError,ValueError) as exc:
                    messages.error(request,'خطای بررسی شاخص‌ها: '+str(exc))
        elif action=='source':
            if not can_source or a.publish_approved:raise PermissionDenied
            try:
                field=request.POST.get('review_field')
                decision=request.POST.get('decision','')
                if field not in ExperienceReviewEvent.ALLOWED:raise ValueError('نوع بررسی نامعتبر است.')
                obj=ExperienceReviewEvent(experience=exp,review_field=field,decision=decision,
                    evidence_url=request.POST.get('evidence_url','').strip(),
                    rationale=request.POST.get('rationale','').strip(),reviewer=request.user)
                obj.save()
                messages.success(request,'تصمیم منبع ثبت شد؛ انتشار عمومی انجام نشده است.')
            except (ValidationError,ValueError) as exc:
                messages.error(request,'خطای بررسی منبع: '+str(exc))
        elif action in {'publish','revoke'}:
            if not can_publish:raise PermissionDenied
            if request.POST.get('confirmed')!='on':
                messages.error(request,'تأیید نهایی مسئولیت انتشار الزامی است.')
            else:
                try:
                    if action=='publish' and a.publish_approved:
                        messages.warning(request,'این ارزیابی قبلاً برای انتشار تأیید شده است.')
                    elif action=='revoke' and not a.publish_approved:
                        messages.warning(request,'این ارزیابی منتشر نشده است.')
                    else:
                        set_publication(request,a.pk,approve=(action=='publish'),
                                        rationale=request.POST.get('rationale',''))
                        messages.success(request,'انتشار AI تأیید شد.' if action=='publish' else 'انتشار AI لغو شد.')
                except ValueError as exc:messages.error(request,str(exc))
        else:
            return HttpResponseNotAllowed(['GET'])
        return HttpResponseRedirect(reverse('admin:assessments_aiassessment_publication_detail',args=[a.pk]))
    # Refresh after POST redirect; no changes ever occur on GET.
    dims={d.key:d for d in a.dimensions.prefetch_related('human_review_events').all()}
    panels=[]
    for key,label in DIMENSIONS:
        d=dims.get(key)
        latest=latest_verdict(d) if d else None
        approved_value = ('yes' if latest and latest.verdict in ('supported', 'correct_abstention')
                          else 'no' if latest else '')
        panels.append({'key':key,'label':label,'dim':d,'latest':latest,
                       'approved_value':approved_value,
                       'needs_manual_source': bool(d and d.score is not None and
                                                   (not d.evidence or not d.explanation.strip()))})
    blockers=preliminary_blockers(a)
    ctx=_context(admin_view,request,f'بررسی و انتشار AI #{a.pk}')
    ctx.update({'assessment':a,'experience':exp,'company':exp.company,
        'panels':panels,'blockers':blockers,'ready':not blockers,
        'needs_rights':exp.copyright_review=='pending',
        'rights_review_url':reverse('admin:experiences_experiencereviewevent_add') + f'?experience={exp.pk}&review_field=copyright',
        'rights_blocked':exp.copyright_review=='blocked',
        'can_review':can_review,'can_source':can_source,'can_publish':can_publish,
        'can_quick_publish':(can_publish and can_review and can_source),
        'source_url':source_url(exp.source_url),
        'verdicts':AiHumanReviewEvent.VERDICTS,'errors':AiHumanReviewEvent.ERROR_TYPES,
        'source_review_rows':[(field,label,[(value,dict(ExperienceReviewEvent.DECISIONS)[value]) for value in sorted(ExperienceReviewEvent.ALLOWED[field])]) for field,label in ExperienceReviewEvent.REVIEW_FIELDS],
        'source_history':list(exp.review_events.select_related('reviewer')[:15]),
        'latest_log':list(LogEntry.objects.filter(
            content_type__app_label='assessments', content_type__model='aiassessment',object_id=str(a.pk))
            .select_related('user').order_by('-action_time')[:8]),
        'queue_url':reverse('admin:assessments_aiassessment_publication_queue'),
        'company_review_url':reverse('admin:companies_company_review',args=[exp.company_id]),
        'experience_url':reverse('admin:companies_company_experience_detail',args=[exp.company_id,exp.pk]),
        'public_company_url':reverse('company-detail',args=[exp.company_id]),
    })
    return _respond(request,'admin/assessments/aiassessment/publication_detail_v104.html',ctx)
