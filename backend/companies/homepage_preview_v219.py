"""Private v2.0.19 integration of the supplied homepage, without mock rankings.

The preview reads only public company metadata. It deliberately does not access
CriteriaAnalysis, CriteriaAxisScore or unpublished rollups. Never replaces /.
"""
import os
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import F
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .models import Company
from criteria_v2.registry import axes_for


def authorize_home_preview(request):
    if os.environ.get('JOBIEW_HOMEPAGE_PREVIEW_ENABLED', '0') != '1':
        raise Http404('Homepage preview disabled')
    if not settings.DEBUG:
        if (os.environ.get('JOBIEW_HOMEPAGE_STAGING_ENABLED', '0') != '1' or
                os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0'):
            raise Http404('Homepage staging disabled')
        expected = os.environ.get('JOBIEW_HOMEPAGE_STAGING_HOST', '').lower().strip()
        if not expected or request.get_host().split(':')[0].lower() != expected or not request.is_secure():
            raise Http404('Homepage staging requires its dedicated HTTPS host')
    user = request.user
    if not (user.is_authenticated and user.is_active and user.is_staff and
            user.has_perm('companies.view_company')):
        raise PermissionDenied('Staff company-view permission required')


@never_cache
@require_GET
def preview(request):
    authorize_home_preview(request)
    q = (request.GET.get('q') or '').strip()[:100]
    mode = request.GET.get('mode', 'work')
    mode = mode if mode in ('work', 'interview') else 'work'
    sort = request.GET.get('sort', 'most')
    sort = sort if sort in ('most', 'name') else 'most'
    verified = request.GET.get('verified') == '1'
    has_records = request.GET.get('has_records') == '1'
    count_field = 'source_work_count' if mode == 'work' else 'source_interview_count'
    queryset = Company.objects.all()
    if q:
        queryset = queryset.filter(display_name__icontains=q)
    if verified:
        queryset = queryset.filter(identity_status='verified', tech_status='verified', tehran_status='verified')
    if has_records:
        queryset = queryset.filter(**{count_field + '__gt': 0})
    queryset = queryset.annotate(experience_count=F(count_field))
    if sort == 'most':
        queryset = queryset.order_by('-experience_count', 'display_name', 'pk')
    else:
        queryset = queryset.order_by('display_name', 'pk')
    page = Paginator(queryset, 24).get_page(request.GET.get('page'))
    response = render(request, 'companies/homepage_preview_v219.html', {
        'page': page, 'q': q, 'mode': mode, 'sort': sort,
        'verified': verified, 'has_records': has_records,
        'criteria_axes': axes_for(mode),
    })
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'no-referrer'
    response['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "font-src 'self' https://cdnjs.cloudflare.com data:; "
        "connect-src 'self' https://tiles.openfreemap.org https://unpkg.com; "
        "worker-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; object-src 'none'"
    )
    return response