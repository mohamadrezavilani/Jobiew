"""Opt-in independent Claude check for the current six-axis GPT-6 framework.

No calls on GET, no batch calls or retries, explicit authorisation/rights
attestation on every paid POST. Never changes reviewed GPT-6 scores.
"""
import os
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from companies.models import Company
from criteria_v2.checkpoint_access_v218 import authorize_checkpoint
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.checkpoint_private_v218 import _private_run_valid
from criteria_v2.engine_v207 import (
    build_request, call_claude, safe_usage, story_digest,
    story_from_experience, validate_response,
)
from criteria_v2.models import CriteriaAnalysis, CriteriaClaudeComparison
from criteria_v2.registry import axes_for

_MODEL = re.compile(r'claude-[a-z0-9-]{4,90}\Z')


def _available():
    try:
        cap = min(100, max(0, int(os.environ.get('JOBIEW_CLAUDE_SIX_LIMIT', '0'))))
    except ValueError:
        cap = 0
    model = os.environ.get('JOBIEW_CLAUDE_SIX_MODEL', 'claude-sonnet-5-5').strip()
    enabled = (os.environ.get('JOBIEW_CLAUDE_SIX_ENABLED', '0') == '1'
               and cap > 0 and bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())
               and bool(_MODEL.fullmatch(model)))
    return enabled, cap, model


def _comparison_rows(analysis, record):
    old = {axis.key: axis for axis in analysis.axis_scores.all()}
    new = record.claude_axes if record and record.status == 'completed' else {}
    result = []
    for axis in axes_for(analysis.experience.source_kind):
        previous = old.get(axis.key)
        ai = new.get(axis.key) if isinstance(new, dict) else None
        score = ai.get('score') if isinstance(ai, dict) else None
        oldscore = previous.score if previous else None
        result.append({
            'label': axis.label, 'key': axis.key,
            'original': oldscore, 'claude': score,
            'delta': (score - oldscore if score is not None and oldscore is not None else None),
            'confidence': ai.get('confidence') if isinstance(ai, dict) else None,
            'explanation': ai.get('explanation', '') if isinstance(ai, dict) else '',
            'evidence': ai.get('evidence', []) if isinstance(ai, dict) else [],
        })
    return result


def _rights_for_external_processing(exp):
    """The source must be reviewed, not merely carry a claimed approval flag."""
    from experiences.models import ExperienceReviewEvent
    latest = (ExperienceReviewEvent.objects.filter(
        experience=exp, review_field='copyright')
        .order_by('-created_at', '-pk').first())
    return bool(
        exp.copyright_review == 'approved' and
        latest and latest.decision == 'approved' and latest.evidence_url
    )


def claude_six_review(admin_view, request, object_id, experience_id):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    authorize_checkpoint(request)
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied
    analysis = (CriteriaAnalysis.objects.filter(
        experience_id=experience_id, experience__company=company,
        raw_payload__engine=ENGINE,
        review_status__in=('pilot_unverified', 'approved', 'no_evaluable_scores'))
        .select_related('experience').prefetch_related('axis_scores')
        .order_by('-created_at', '-pk').first())
    if analysis is None:
        raise Http404('No GPT-6 checkpoint for this experience')
    exp = analysis.experience
    story = story_from_experience(exp)
    valid = _private_run_valid(analysis, story)
    existing = (CriteriaClaudeComparison.objects
                .filter(analysis=analysis).select_related('requested_by').first())
    can_run = request.user.has_perm('criteria_v2.add_criteriaclaudecomparison')
    enabled, limit, model = _available()
    used = CriteriaClaudeComparison.objects.count()
    source_rights = _rights_for_external_processing(exp)
    url = reverse('admin:companies_company_experience_claude',
                  args=[company.pk, exp.pk])
    back = reverse('admin:companies_company_experience_detail',
                   args=[company.pk, exp.pk])
    if request.method == 'POST':
        if not can_run:
            raise PermissionDenied
        if existing:
            messages.info(request, 'نتیجهٔ قبلی Claude ثبت شده است؛ اجرای مجدد خودکار انجام نمی‌شود.')
            return redirect(url)
        if (request.POST.get('confirm_paid') != 'yes' or
                request.POST.get('confirm_external_rights') != 'yes'):
            messages.error(request, 'اجازهٔ ارسال به سرویس بیرونی و هزینهٔ احتمالی باید صریحاً تأیید شود.')
            return redirect(url)
        if not source_rights:
            messages.error(request, 'مدرک حق استفاده از منبع برای این تجربه ثبت نشده است؛ ارسال بیرونی مجاز نیست.')
            return redirect(url)
        if not valid or not enabled or used >= limit:
            messages.error(request, 'اجرای Claude غیرفعال یا سهمیه تمام است، یا شواهد شش‌معیاری معتبر نیست.')
            return redirect(url)
        if len(story.strip()) < 50:
            messages.error(request, 'متن این تجربه برای بررسی مستقل کافی نیست.')
            return redirect(url)
        # One reservation per analysis. Lock its company to serialize starts
        # within one company; unique FK prevents double charge for that case.
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=company.pk)
            if CriteriaClaudeComparison.objects.filter(analysis=analysis).exists():
                messages.info(request, 'بررسی قبلاً ثبت شده است.')
                return redirect(url)
            if CriteriaClaudeComparison.objects.count() >= limit:
                messages.error(request, 'سهمیهٔ اجرای مدل تکمیل شده است.')
                return redirect(url)
            record = CriteriaClaudeComparison.objects.create(
                analysis=analysis, requested_by=request.user,
                model_id=model, source_content_sha256=exp.content_sha256,
                story_sha256=story_digest(story))
        result = {}
        error = ''
        try:
            response = call_claude(build_request(exp.source_kind, story, model))
            result = validate_response(response, kind=exp.source_kind, story=story)
            usage = safe_usage(response)
        except Exception as exc:
            # Never persist raw model responses, credentials, URLs or story text.
            result = {}
            usage = {}
            error = type(exc).__name__[:64]
        # Recheck source integrity before ever showing the model output.
        exp.refresh_from_db()
        safe = (
            exp.content_sha256 == record.source_content_sha256 and
            story_digest(story_from_experience(exp)) == record.story_sha256)
        status = (
            'failed' if error or not safe else
            'completed' if result.get('status') == 'unreviewed' else
            'needs_review')
        updated = {
            'status': status,
            'detected_kind': result.get('detected_kind', '') if safe else '',
            'claude_axes': result.get('dimensions') or {} if safe and not error else {},
            'comparison': {},
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
            'error_type': error or ('SOURCE_CHANGED' if not safe else ''),
            'completed_at': timezone.now(),
        }
        CriteriaClaudeComparison.objects.filter(pk=record.pk, status='running').update(**updated)
        messages.success(request,
            'نتیجهٔ بررسی مستقل Claude ثبت شد؛ نمره‌های GPT-6 و وضعیت انتشار تغییری نکرد.'
            if status == 'completed' else
            'بررسی Claude پایان یافت اما نتیجه نیازمند بررسی است؛ نمره‌ها تغییر نکردند.')
        return redirect(url)

    current = bool(existing and existing.story_sha256 == story_digest(story)
                   and existing.source_content_sha256 == exp.content_sha256)
    ctx = {
        **admin_view.admin_site.each_context(request),
        'title': 'بررسی مستقل Claude — ' + exp.title[:80],
        'opts': admin_view.model._meta,
        'company': company, 'experience': exp, 'analysis': analysis,
        'valid_analysis': valid, 'existing': existing,
        'current': current,
        'rows': _comparison_rows(analysis, existing) if current and valid else [],
        'enabled': enabled, 'can_run': can_run, 'rights_ready': source_rights,
        'model': model, 'limit': limit, 'used': used,
        'back_url': back, 'review_url': url,
    }
    reply = TemplateResponse(request,
        'admin/companies/company/claude_six_v233.html', ctx)
    reply['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    reply['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    reply['Referrer-Policy'] = 'same-origin'
    return reply
