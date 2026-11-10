"""Admin-only Claude 6+6 comparison for a company's work/interview source."""
import os
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from .company_experiences_admin_v103 import (
    _company_and_access, _context, _safe_source_url, _six_runs,
)
from criteria_v2.claude_six_v233 import (
    allowed, check_one, enabled, _limit, _model,
)
from criteria_v2.models import CriteriaClaudeValidationRun
from criteria_v2.registry import axes_for
from criteria_v2.engine_v207 import story_from_experience
from criteria_v2.checkpoint_private_v218 import _private_run_valid
from experiences.models import PublicExperience


def claude_six_detail(admin_view, request, object_id, experience_id):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    company = _company_and_access(admin_view, request, object_id)
    if not allowed(request):
        raise PermissionDenied('Claude six-axis audit view permission required')
    exp = get_object_or_404(PublicExperience, pk=experience_id, company_id=company.pk)
    exp.safe_source_url = _safe_source_url(exp.source_url)
    analysis = _six_runs([exp]).get(exp.pk)
    valid = bool(analysis and _private_run_valid(
        analysis, story_from_experience(exp)))
    url = reverse('admin:companies_company_experience_claude',
                  args=[company.pk, exp.pk])
    if request.method == 'POST':
        if not allowed(request, run=True):
            raise PermissionDenied('Claude six-axis run permission required')
        if request.POST.get('confirm_paid') != 'yes':
            messages.error(request, 'برای فراخوانی پولی باید تأیید صریح ثبت شود.')
        elif not valid:
            messages.error(request, 'شش معیار یا متن فعلی معتبر نیست؛ فراخوانی انجام نشد.')
        else:
            try:
                result, called = check_one(
                    request, analysis.pk, force=request.POST.get('force') == 'yes')
                if result.status == 'completed':
                    messages.success(request, 'مقایسه Claude ثبت شد.' if called
                                     else 'مقایسهٔ قبلی موجود است؛ فراخوانی جدیدی انجام نشد.')
                else:
                    messages.error(request, 'فراخوانی ناموفق بود (' + result.error_type +
                                   ')؛ درخواست تکراری خودکار ارسال نمی‌شود.')
            except (ValueError, PermissionError) as exc:
                messages.error(request, str(exc))
        return redirect(url)
    history = list(CriteriaClaudeValidationRun.objects.filter(
        analysis=analysis).select_related('requested_by').order_by('-pk')[:12]) if analysis else []
    latest = next((run for run in history if run.status == 'completed'), None)
    axes = axes_for(exp.source_kind)
    originals = ({row.key: row for row in analysis.axis_scores.all()}
                 if analysis and valid else {})
    rows = []
    compared = latest.comparison if latest and isinstance(latest.comparison, dict) else {}
    for axis in axes:
        rows.append({'axis': axis, 'original': originals.get(axis.key),
                     'compared': compared.get(axis.key)})
    quota = _limit()
    used = CriteriaClaudeValidationRun.objects.count()
    config_ok = enabled() and bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())
    can_execute = valid and config_ok and used < quota and allowed(request, run=True)
    stale = bool(latest and latest.source_content_sha256 != exp.content_sha256)
    ctx = _context(admin_view, request, company,
                   'بررسی مستقل Claude: ' + exp.title[:80])
    ctx.update({
        'experience': exp, 'analysis': analysis, 'rows': rows, 'history': history,
        'latest': latest, 'stale': stale, 'integrity_ok': valid,
        'model_id': _model(), 'enabled': enabled(),
        'key_ready': bool(os.environ.get('ANTHROPIC_API_KEY', '').strip()),
        'quota': quota, 'used': used, 'remaining': max(0, quota - used),
        'can_execute': can_execute,
        'detail_url': reverse('admin:companies_company_experience_detail',
                              args=[company.pk, exp.pk]),
    })
    response = TemplateResponse(request,
        'admin/companies/company/claude_six_detail_v233.html', ctx)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'same-origin'
    return response
