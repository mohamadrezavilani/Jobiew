"""Read-only, company-scoped source experiences in the staff admin.

No publication flags, AI scores, provenance or review decisions are modified.
"""
from urllib.parse import urlencode, urlsplit

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from assessments.models import AiAssessment, DIMENSIONS, FIVE_CRITERIA_VERSION
from companies.models import Company
from experiences.models import PublicExperience

PAGE_SIZE = 20
KIND_FILTERS = {'all': 'همه محتواها', 'work': 'تجربه کاری', 'interview': 'مصاحبه'}
COPYRIGHT_FILTERS = {'all': 'همه', 'pending': 'بررسی نشده', 'approved': 'تأیید مرحله حقوقی', 'blocked': 'غیرمجاز'}
ATTRIBUTION_FILTERS = {'all': 'همه', 'unverified': 'تأیید نشده', 'verified': 'تأییدشده', 'rejected': 'ردشده'}
INDEPENDENCE_FILTERS = {'all': 'همه', 'unknown': 'نامشخص', 'verified': 'مستقل', 'duplicate': 'تکراری'}


def _safe_source_url(raw):
    """Untrusted source URLs cannot become executable href values."""
    try:
        parts = urlsplit(raw or '')
        if parts.scheme.lower() in {'http', 'https'} and parts.hostname:
            return raw
    except ValueError:
        pass
    return ''


def _company_and_access(admin_view, request, object_id):
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied
    if not request.user.has_perm('experiences.view_publicexperience'):
        raise PermissionDenied
    return company


def _context(admin_view, request, company, title):
    return {
        **admin_view.admin_site.each_context(request),
        'title': title,
        'company': company,
        'opts': admin_view.model._meta,
        'has_view_permission': True,
        'source_company_url': company.source_url,
        'company_change_url': reverse('admin:companies_company_change', args=[company.pk]),
        'company_review_url': reverse('admin:companies_company_review', args=[company.pk]),
        'company_experiences_url': reverse('admin:companies_company_experiences', args=[company.pk]),
    }


def company_experiences(admin_view, request, object_id):
    """Fast paginated browser; source counts are NOT presented as DB counts."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    company = _company_and_access(admin_view, request, object_id)
    q = (request.GET.get('q') or '').strip()[:120]
    kind = request.GET.get('kind', 'all')
    copyright_status = request.GET.get('copyright', 'all')
    attribution = request.GET.get('attribution', 'all')
    independence = request.GET.get('independence', 'all')
    if kind not in KIND_FILTERS:
        kind = 'all'
    if copyright_status not in COPYRIGHT_FILTERS:
        copyright_status = 'all'
    if attribution not in ATTRIBUTION_FILTERS:
        attribution = 'all'
    if independence not in INDEPENDENCE_FILTERS:
        independence = 'all'

    base = PublicExperience.objects.filter(company_id=company.pk)
    totals = base.aggregate(
        total=Count('pk'),
        work=Count('pk', filter=Q(source_kind='work')),
        interview=Count('pk', filter=Q(source_kind='interview')),
    )
    qs = base
    if kind != 'all':
        qs = qs.filter(source_kind=kind)
    if copyright_status != 'all':
        qs = qs.filter(copyright_review=copyright_status)
    if attribution != 'all':
        qs = qs.filter(company_attribution_status=attribution)
    if independence != 'all':
        qs = qs.filter(independence_status=independence)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q) |
                       Q(job_title__icontains=q) | Q(source_url__icontains=q))

    page = Paginator(qs.order_by('-imported_at', '-pk'), PAGE_SIZE).get_page(request.GET.get('page', '1'))
    page.object_list = list(page.object_list)
    for exp in page.object_list:
        exp.safe_source_url = _safe_source_url(exp.source_url)
    params = {'q': q, 'kind': kind, 'copyright': copyright_status,
              'attribution': attribution, 'independence': independence}
    query = urlencode({k: v for k, v in params.items() if v and v != 'all'})
    ctx = _context(admin_view, request, company, 'تجربه‌ها و مصاحبه‌های ' + company.display_name)
    ctx.update({
        'page_obj': page, 'totals': totals, 'q': q,
        'kind': kind, 'copyright_status': copyright_status,
        'attribution': attribution, 'independence': independence,
        'kind_filters': KIND_FILTERS, 'copyright_filters': COPYRIGHT_FILTERS,
        'attribution_filters': ATTRIBUTION_FILTERS,
        'independence_filters': INDEPENDENCE_FILTERS,
        'page_query': (query + '&') if query else '',
    })
    return TemplateResponse(request, 'admin/companies/company/experiences_list_v103.html', ctx)


def company_experience_detail(admin_view, request, object_id, experience_id):
    """Staff-only full source body with optional five_v1 AI review, never public."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    company = _company_and_access(admin_view, request, object_id)
    exp = get_object_or_404(PublicExperience, pk=experience_id, company_id=company.pk)
    exp.safe_source_url = _safe_source_url(exp.source_url)
    can_ai = (request.user.has_perm('assessments.view_aiassessment') and
              request.user.has_perm('assessments.view_aidimension'))
    assessments = []
    if can_ai:
        assessments = list(AiAssessment.objects.filter(
            experience_id=exp.pk, criteria_version=FIVE_CRITERIA_VERSION
        ).prefetch_related('dimensions').order_by('-created_at', '-pk')[:10])
        labels = dict(DIMENSIONS)
        for assessment in assessments:
            assessment.display_dimensions = sorted(assessment.dimensions.all(),
                key=lambda d: list(labels).index(d.key) if d.key in labels else 99)
            for dim in assessment.display_dimensions:
                dim.display_label = labels.get(dim.key, dim.key)
    ctx = _context(admin_view, request, company, 'متن تجربه: ' + exp.title[:100])
    ctx.update({'experience': exp, 'assessments': assessments, 'can_see_ai': can_ai})
    return TemplateResponse(request, 'admin/companies/company/experience_detail_v103.html', ctx)
