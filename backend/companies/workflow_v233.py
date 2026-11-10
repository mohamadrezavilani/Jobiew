"""Company-centred single-page operational progress and next action.

The overview never changes a decision; it reads the same immutable review,
rights and publication predicates as release and public views.
"""
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from .models import Company
from .map_visibility_v232 import company_map_status
from criteria_v2.checkpoint_access_v218 import authorize_checkpoint
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.models import CriteriaAnalysis
from criteria_v2.company_release_v224 import publication_candidates
from criteria_v2.publication_state_v231 import company_publication_state


def company_workflow(admin_view, request, object_id):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    authorize_checkpoint(request)
    if not admin_view.has_view_permission(request):
        raise PermissionDenied
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied
    from experiences.models import PublicExperience
    total = PublicExperience.objects.filter(company=company).count()
    runs = (CriteriaAnalysis.objects.filter(
        experience__company=company, raw_payload__engine=ENGINE))
    counts = runs.aggregate(
        total=Count('pk'),
        pending=Count('pk', filter=Q(review_status='pilot_unverified')),
        approved=Count('pk', filter=Q(review_status='approved')),
        abstained=Count('pk', filter=Q(review_status='no_evaluable_scores')),
    )
    try:
        proofs, stats = publication_candidates(company)
        publication_error = False
    except ValueError:
        proofs, stats = {}, None
        publication_error = True
    state = company_publication_state(company)
    location = company_map_status(company)

    def step(label, complete, description, url, action):
        return {'label': label, 'complete': bool(complete),
                'description': description, 'url': url, 'action': action}

    verification_ok = (
        company.identity_status == 'verified' and company.tech_status == 'verified')
    rows = [
        step('۱. دریافت تجربه‌ها', total > 0,
             f'{total} تجربه یا مصاحبه در دیتابیس موجود است. '
             'ورود فایل جدید از مسیر کنترل‌شدهٔ import انجام می‌شود، نه با تأیید ساختگی در ادمین.',
             reverse('admin:companies_company_experiences', args=[company.pk]),
             'دیدن تجربه‌های واردشده'),
        step('۲. بازبینی شش‌معیاری GPT-6',
             counts['total'] > 0 and counts['pending'] == 0,
             f'{counts["approved"]} پروندهٔ دارای نمره و {counts["abstained"]} بدون شاهد عددی '
             f'بازبینی شده‌اند؛ {counts["pending"]} پرونده در انتظار است.',
             reverse('admin:companies_company_checkpoint_bulk', args=[company.pk]),
             'بازبینی امتیازها'),
        step('۳. تأیید شرکت', verification_ok,
             'هویت و فناوری شرکت باید با مدرک واقعی بررسی شوند.',
             reverse('admin:companies_company_checkpoint_verify', args=[company.pk]),
             'بررسی شرکت'),
        step('۴. بررسی منبع و دسته‌بندی',
             bool(stats and stats['blocked_provenance'] == 0),
             ('هیچ نقصی برای پرونده‌های بازبینی‌شدهٔ نمره‌دار ثبت نشده است.'
              if stats and stats['blocked_provenance'] == 0 else
              (f'{stats["blocked_provenance"]} پرونده نیازمند مدارک است؛ '
               f'{stats["copyright_missing"]} مجوز منبع ناقص.'
               if stats else 'تعداد پرونده‌ها از سقف بررسی ایمن بیشتر است.')),
             reverse('admin:companies_company_checkpoint_sources', args=[company.pk]),
             'بررسی گروهی مدارک'),
        step('۵. انتشار امتیازهای مجاز', state['visible_now'],
             (f'{state["recorded_count"]} پرونده در تصمیم انتشار و '
              f'{state["visible_experiences"]} تجربه در خروجی عمومی قابل نمایش است. '
              + state['reason']),
             reverse('admin:companies_company_checkpoint_release', args=[company.pk]),
             'بررسی انتشار'),
    ]
    primary = next((row for row in rows if not row['complete']), None)
    if primary is None:
        primary = {'label': 'کار اصلی برای پرونده‌های فعلی تکمیل شده است',
                   'url': reverse('admin:companies_company_checkpoint_release',
                                  args=[company.pk]),
                   'action': 'مشاهدهٔ نتیجه'}
    ctx = {
        **admin_view.admin_site.each_context(request),
        'title': 'مسیر سادهٔ مدیریت ' + company.display_name,
        'company': company, 'steps': rows,
        'next': primary, 'counts': counts,
        'total_experiences': total,
        'unscored_experiences': max(0, total - counts['total']),
        'ready_count': len(proofs), 'public_state': state,
        'location_state': location,
        'publication_error': publication_error,
        'public_url': reverse('company-detail', args=[company.pk]) + '?tab=ai',
        'opts': admin_view.model._meta,
        'has_view_permission': True,
    }
    response = TemplateResponse(request,
        'admin/companies/company/workflow_v233.html', ctx)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'same-origin'
    return response
