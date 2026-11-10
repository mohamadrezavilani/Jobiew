"""Company-scoped staff UI for optional six-axis Claude second opinions."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from companies.models import Company
from .checkpoint_access_v218 import authorize_checkpoint
from .claude_six_models_v233 import ClaudeSixCheck
from .claude_six_v233 import (enabled, configured_limit, valid_analysis,
                              can_send_source, comparison_rows, run_one)
from .models import CriteriaAnalysis
from .checkpoint_contract_v218 import ENGINE
from .registry import axes_for


def company_claude_review(admin_view, request, object_id, experience_id):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    authorize_checkpoint(request)
    if not all(request.user.has_perm(p) for p in (
            'companies.view_company', 'experiences.view_publicexperience',
            'criteria_v2.view_criteriaanalysis',
            'criteria_v2.view_criteriaaxisscore',
            'criteria_v2.view_claudesixcheck')):
        raise PermissionDenied('Independent six-axis audit permission required')
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied
    analysis = (CriteriaAnalysis.objects.filter(
        experience_id=experience_id, experience__company=company,
        raw_payload__engine=ENGINE,
        review_status__in=('pilot_unverified','approved','no_evaluable_scores'))
        .select_related('experience')
        .prefetch_related('axis_scores')
        .order_by('-created_at','-pk').first())
    if analysis is None:
        # This experience may exist, but no GPT-6 six-axis proposal does.
        from django.http import Http404
        raise Http404('GPT-6 checkpoint not found for this company experience')
    detail_url = reverse(
        'admin:companies_company_experience_detail',
        args=[company.pk, experience_id])
    same_url = reverse(
        'admin:companies_company_claude_six',
        args=[company.pk, experience_id])
    previous = ClaudeSixCheck.objects.filter(analysis=analysis).first()
    integrity = valid_analysis(analysis)
    rights = can_send_source(analysis.experience)
    can_run = bool(
        enabled() and integrity and rights and previous is None
        and request.user.has_perm('criteria_v2.add_claudesixcheck')
        and ClaudeSixCheck.objects.count() < configured_limit())
    if request.method == 'POST':
        if not request.user.has_perm('criteria_v2.add_claudesixcheck'):
            raise PermissionDenied
        if request.POST.get('confirm_external') != 'yes':
            messages.error(request, 'قبل از اجرای پولی Claude، ارسال متن و هزینهٔ آن را صریحاً تأیید کن.')
        elif not can_run:
            messages.error(request, 'اجرای جدید مجاز نیست؛ وضعیت دسترسی، مجوز منبع یا نتیجهٔ قبلی را بررسی کن.')
        else:
            try:
                result, called = run_one(analysis, request.user)
                if not called:
                    messages.info(request, 'نتیجهٔ قبلی موجود است؛ فراخوانی تکراری انجام نشد.')
                elif result.status == 'completed':
                    messages.success(request, 'بررسی مستقل Claude ذخیره شد. نتیجهٔ شش محور در همین صفحه قابل مشاهده است.')
                elif result.status == 'needs_review':
                    messages.warning(request, 'Claude در تشخیص نوع تجربه اختلاف دارد؛ نتیجه صرفاً برای بررسی انسانی ذخیره شد.')
                else:
                    messages.error(request, 'فراخوانی Claude ناموفق بود؛ کد وضعیت بدون محتوای خصوصی ذخیره شد.')
            except ValueError as exc:
                messages.error(request, str(exc))
        return redirect(same_url)

    rows, current = comparison_rows(
        analysis, previous) if previous is not None else ([], False)
    axes = axes_for(analysis.experience.source_kind)
    response = TemplateResponse(request,
        'admin/companies/company/claude_six_v233.html', {
            **admin_view.admin_site.each_context(request),
            'title': 'مقایسهٔ GPT-6 با Claude',
            'company': company,
            'experience': analysis.experience,
            'analysis': analysis,
            'integrity': integrity,
            'rights': rights,
            'enabled': enabled(),
            'quota': configured_limit(),
            'used': ClaudeSixCheck.objects.count(),
            'can_run': can_run,
            'previous': previous,
            'rows': rows if previous and previous.status == 'completed' and current else [],
            'current': current,
            'axes': axes,
            'detail_url': detail_url,
            'same_url': same_url,
            'opts': admin_view.model._meta,
            'has_view_permission': True,
        })
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'same-origin'
    return response
