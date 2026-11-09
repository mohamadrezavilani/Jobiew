"""Staff-only, evidence-gated 6+6 proposal adjudication (v2.0.9).

AI scores are never published or accepted automatically. A reviewer must
explicitly decide the six axes, and every decision has an append-only event.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from django.core.paginator import Paginator

from experiences.models import PublicExperience
from .engine_v207 import story_digest, story_from_experience
from .models import (CriteriaAnalysis, CriteriaAxisScore, CriteriaReviewEvent,
                     CriteriaScoreReviewEvent)
from .registry import axes_for, version_for


def _staff_guard(request, *, write=False):
    u = request.user
    required = ('experiences.view_publicexperience', 'criteria_v2.view_criteriaanalysis')
    if not (u.is_authenticated and u.is_active and u.is_staff and
            all(u.has_perm(p) for p in required)):
        raise PermissionDenied('Staff review permissions required')
    if write and not u.has_perm('criteria_v2.add_criteriascorereviewevent'):
        raise PermissionDenied('Staff score adjudication permission required')


def _private_response(request, template, context):
    response = render(request, template, context)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


def _current_confirmation(exp):
    return (CriteriaReviewEvent.objects.filter(
        experience_id=exp.pk, source_kind=exp.source_kind,
        criteria_version=version_for(exp.source_kind),
    ).order_by('-created_at', '-pk')
        .values_list('decision', 'source_content_sha256').first())


def _eligible(analysis, exp, story):
    if (analysis.review_status != 'unreviewed' or
        analysis.criteria_version != version_for(exp.source_kind) or
        analysis.source_content_sha256 != exp.content_sha256 or
        exp.copyright_review != 'approved' or
        exp.company_attribution_status != 'verified' or
        exp.independence_status == 'duplicate' or
        _current_confirmation(exp) != ('confirmed', exp.content_sha256)):
        return False
    payload = analysis.raw_payload
    return (isinstance(payload, dict) and
            payload.get('engine') == 'jobiew_dual6_evidence_v207' and
            payload.get('story_sha256') == story_digest(story))


def _rows(analysis, story):
    """Require exactly six unique, key-correct items; no partial model output."""
    expected = tuple(axes_for(analysis.experience.source_kind))
    found = list(analysis.axis_scores.all())
    if len(found) != 6 or {r.key for r in found} != {axis.key for axis in expected}:
        raise ValueError('INCOMPLETE_SIX_AXIS_OUTPUT')
    by_key = {r.key: r for r in found}
    checked = []
    for axis in expected:
        item = by_key[axis.key]
        if item.semantic_status != 'unreviewed':
            raise ValueError('AXIS_ALREADY_ADJUDICATED')
        if item.score is None:
            if item.confidence != 0 or item.evidence not in ([], None):
                raise ValueError('INVALID_ABSTENTION')
            options = ('abstain',)
        else:
            if type(item.score) is not int or not 1 <= item.score <= 10:
                raise ValueError('INVALID_SCORE')
            if type(item.confidence) is not int or not 70 <= item.confidence <= 100:
                raise ValueError('INVALID_CONFIDENCE')
            quotes = item.evidence
            if (not isinstance(quotes, list) or not quotes or
                not all(isinstance(q, str) and 12 <= len(q) <= 450 and q in story
                        and not any(p in q for p in ('[email]', '[phone]', '[number]'))
                        for q in quotes)):
                raise ValueError('INVALID_EVIDENCE')
            options = ('approve', 'reject')
        checked.append({'axis': axis, 'item': item, 'options': options})
    return checked


@never_cache
@require_GET
def queue(request):
    _staff_guard(request)
    pending = (CriteriaAnalysis.objects.filter(review_status='unreviewed')
               .select_related('experience', 'experience__company')
               .order_by('created_at', 'pk'))
    page = Paginator(pending, 30).get_page(request.GET.get('page'))
    return _private_response(request, 'criteria_v2/score_review_queue_v209.html',
                             {'page': page})


@never_cache
@require_http_methods(['GET', 'POST'])
def detail(request, analysis_id):
    _staff_guard(request, write=request.method == 'POST')
    if request.method == 'GET':
        analysis = get_object_or_404(CriteriaAnalysis.objects.select_related(
            'experience', 'experience__company').prefetch_related('axis_scores'),
            pk=analysis_id)
        story = story_from_experience(analysis.experience)
        eligible = _eligible(analysis, analysis.experience, story)
        try:
            rows = _rows(analysis, story) if eligible else []
        except ValueError:
            rows, eligible = [], False
        return _private_response(request, 'criteria_v2/score_review_detail_v209.html',
                                 {'analysis': analysis, 'story': story, 'eligible': eligible,
                                  'rows': rows})
    note = (request.POST.get('note') or '').strip()
    if not 12 <= len(note) <= 1500:
        return HttpResponseBadRequest('Review rationale must be 12..1500 characters')
    with transaction.atomic():
        # Lock the source before the analysis to serialize with other reviews.
        target = get_object_or_404(CriteriaAnalysis, pk=analysis_id)
        exp = PublicExperience.objects.select_for_update().get(pk=target.experience_id)
        analysis = CriteriaAnalysis.objects.select_for_update().select_related(
            'experience').get(pk=analysis_id)
        story = story_from_experience(exp)
        if not _eligible(analysis, exp, story):
            return HttpResponse('STALE_OR_INELIGIBLE_ANALYSIS', status=409)
        try:
            rows = _rows(analysis, story)
        except ValueError:
            return HttpResponse('INVALID_ANALYSIS_EVIDENCE', status=409)
        choices = {}
        approved = 0
        for row in rows:
            key = row['axis'].key
            decision = request.POST.get('axis_' + key)
            if decision not in row['options']:
                return HttpResponseBadRequest('Invalid or missing six-axis review decision')
            choices[key] = decision
            approved += int(decision == 'approve')
        if request.POST.get('source_sha256') != exp.content_sha256:
            return HttpResponse('STALE_REVIEW_FORM', status=409)
        # Approval decisions and audit event commit atomically.
        for row in rows:
            decision = choices[row['axis'].key]
            state = {'approve': 'approved', 'reject': 'rejected', 'abstain': 'abstained'}[decision]
            CriteriaAxisScore.objects.filter(pk=row['item'].pk).update(semantic_status=state)
        CriteriaAnalysis.objects.filter(pk=analysis.pk).update(
            review_status='approved' if approved else 'no_evaluable_scores')
        CriteriaScoreReviewEvent.objects.create(
            analysis=analysis, reviewer=request.user, source_content_sha256=exp.content_sha256,
            decisions=choices, note=note)
    messages.success(request, 'تصمیم شش‌معیاری ثبت شد؛ انتشار عمومی فعال نشده است.')
    return redirect('dual-score-review-queue')
