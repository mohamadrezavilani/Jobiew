"""Staff-only pilot *review* queue, derived from observable source coverage.

PRD 0.1 sections 6/16 leave pilot admission criteria OPEN. This page never
selects a pilot, verifies a company, or changes public publication state.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, F, OuterRef, Q, Subquery
from django.template.response import TemplateResponse
from django.urls import reverse

from companies.models import Company
from locations.models import CompanyLocation, CompanyLocationReviewEvent


STAGES = {
    'pending': 'در صف بررسی',
    'unreviewed': 'بدون تأیید فعلی',
    'partial': 'بخشی از بررسی انجام شده',
    'map_ready': 'دارای شروط کامل نقشه',
    'rejected': 'دارای تصمیم رد',
    'all': 'همه شرکت‌ها',
}
SORTS = {'work': 'تعداد تجربه کاری (بیشتر)', 'name': 'نام شرکت'}
COVERAGE = {'any': 'همه پوشش‌ها', 'one': 'حداقل ۱ تجربه کاری',
            'five': 'حداقل ۵ تجربه کاری', 'ten': 'حداقل ۱۰ تجربه کاری'}


def _companies_with_map_condition():
    """Match public GeoJSON gates, including last reviewed location evidence.

    Annotate only; do not copy/modify verification decisions, and do not
    confuse a positive current cache with the latest append-only decision.
    """
    latest = CompanyLocationReviewEvent.objects.filter(
        company_id=OuterRef('company_id')
    ).order_by('-created_at', '-pk')
    valid_location = CompanyLocation.objects.filter(
        company_id=OuterRef('pk'), verification_status='verified',
        verified_at__isnull=False, latitude__isnull=False, longitude__isnull=False,
    ).exclude(evidence_url='').annotate(
        last_decision=Subquery(latest.values('decision')[:1]),
        last_lat=Subquery(latest.values('latitude')[:1]),
        last_lon=Subquery(latest.values('longitude')[:1]),
        last_evidence=Subquery(latest.values('evidence_url')[:1]),
    ).filter(
        last_decision='verified', last_lat=F('latitude'),
        last_lon=F('longitude'), last_evidence=F('evidence_url'),
    )
    return Company.objects.select_related('location').annotate(
        valid_location=Exists(valid_location),
    ).annotate(
        map_ready=Exists(valid_location) & Q(identity_status='verified')
        & Q(tech_status='verified') & Q(tehran_status='verified'),
    )


def _unreviewed_condition():
    return (
        Q(identity_status='unverified', tech_status='unverified', tehran_status='unverified')
        & (Q(location__isnull=True) | Q(location__verification_status='unverified'))
    )


def _rejected_condition():
    return (
        Q(identity_status='rejected') | Q(tech_status='rejected')
        | Q(tehran_status='rejected') | Q(location__verification_status='rejected')
    )


def pilot_review_queue(admin_view, request):
    """GET-only, requires same permission as per-company review dashboard."""
    if not admin_view.has_view_permission(request):
        raise PermissionDenied
    if request.method != 'GET':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET'])

    q = (request.GET.get('q') or '').strip()[:100]
    stage = request.GET.get('stage', 'pending')
    if stage not in STAGES:
        stage = 'pending'
    coverage = request.GET.get('coverage', 'any')
    if coverage not in COVERAGE:
        coverage = 'any'
    sort = request.GET.get('sort', 'work')
    if sort not in SORTS:
        sort = 'work'

    qs = _companies_with_map_condition()
    total_companies = Company.objects.count()
    if q:
        qs = qs.filter(Q(display_name__icontains=q) | Q(source_name__icontains=q))
    if coverage != 'any':
        qs = qs.filter(source_work_count__gte={'one': 1, 'five': 5, 'ten': 10}[coverage])

    rejected = _rejected_condition()
    unreviewed = _unreviewed_condition()
    if stage == 'pending':
        qs = qs.exclude(rejected).filter(map_ready=False)
    elif stage == 'unreviewed':
        qs = qs.filter(unreviewed)
    elif stage == 'partial':
        qs = qs.exclude(rejected).exclude(unreviewed).filter(map_ready=False)
    elif stage == 'map_ready':
        qs = qs.filter(map_ready=True)
    elif stage == 'rejected':
        qs = qs.filter(rejected)

    if sort == 'name':
        qs = qs.order_by('display_name', 'pk')
    else:
        qs = qs.order_by('-source_work_count', '-source_interview_count', 'display_name', 'pk')
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    rows = []
    for company in page.object_list:
        location = getattr(company, 'location', None)
        statuses = (company.identity_status, company.tech_status, company.tehran_status,
                    location.verification_status if location else 'unverified')
        rows.append({
            'company': company,
            'statuses': statuses,
            'verified_count': sum(x == 'verified' for x in statuses),
            'map_ready': company.map_ready,
            'review_url': reverse('admin:companies_company_review', args=[company.pk]),
        })
    # Preserve only validated options in navigation, avoiding untrusted URL injection.
    shared = {'q': q, 'stage': stage, 'coverage': coverage, 'sort': sort}
    nav_without_page = urlencode(shared)
    ctx = {
        **admin_view.admin_site.each_context(request),
        'title': 'صف بررسی نامزدهای پایلوت',
        'opts': admin_view.model._meta,
        'rows': rows, 'page': page, 'total_companies': total_companies,
        'matched_count': page.paginator.count, 'query': q,
        'stage': stage, 'coverage': coverage, 'sort': sort,
        'stages': STAGES.items(), 'coverages': COVERAGE.items(), 'sorts': SORTS.items(),
        'nav_without_page': nav_without_page,
        'review_list_url': reverse('admin:companies_company_changelist'),
    }
    return TemplateResponse(request, 'admin/companies/company/pilot_review_queue_v48.html', ctx)
