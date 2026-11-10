"""Read-only, staff-only inspection of *unverified* dual-six private pilot data.

It does not authorize, approve, publish, export, or recalculate any scores.
Only explicitly enabled DEBUG environments can open it; never public endpoints.
"""
import os

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .engine_v207 import story_digest, story_from_experience
from .models import CriteriaAnalysis
from .pilot_import_v212 import ENGINE
from .registry import axes_for, version_for


_PRIVATE_PERMISSIONS = (
    'experiences.view_publicexperience',
    'criteria_v2.view_criteriaanalysis',
    'criteria_v2.view_criteriaaxisscore',
)


def _authorize(request):
    # Deployment defaults must keep this endpoint closed, even to staff.
    if (not settings.DEBUG or
        os.environ.get('JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED', '0') != '1' or
        os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') == '1'):
        raise Http404('Private pilot viewer disabled')
    user = request.user
    if not (user.is_authenticated and user.is_active and user.is_staff and
            all(user.has_perm(permission) for permission in _PRIVATE_PERMISSIONS)):
        raise PermissionDenied('Private pilot read permissions required')


def _private(request, template, context):
    response = render(request, template, context)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'no-referrer'
    # Built-in admin assets remain same-origin only; permit genuine same-origin
    # form submissions. No third-party scripts, frames or network access.
    response['Content-Security-Policy'] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; img-src 'self' data:; font-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
    return response


def _only_pilot():
    return CriteriaAnalysis.objects.filter(
        review_status='pilot_unverified', raw_payload__engine=ENGINE,
    )


@never_cache
@require_GET
def index(request):
    _authorize(request)
    kind = request.GET.get('kind', '').strip()
    company = request.GET.get('company', '').strip()
    if kind not in ('', 'work', 'interview'):
        return HttpResponseBadRequest('Invalid experience kind')
    if len(company) > 24 or any(not (ch.isascii() and (ch.isalnum() or ch in '_-')) for ch in company):
        return HttpResponseBadRequest('Invalid company identifier')
    qs = _only_pilot()
    if kind:
        qs = qs.filter(experience__source_kind=kind)
    if company:
        qs = qs.filter(experience__company_id=company)
    summary = qs.aggregate(
        cases=Count('pk', distinct=True),
        numeric=Count('axis_scores', filter=Q(axis_scores__score__isnull=False)),
        abstentions=Count('axis_scores', filter=Q(axis_scores__score__isnull=True)),
    )
    page = Paginator(
        qs.select_related('experience', 'experience__company').annotate(
            numeric_count=Count('axis_scores', filter=Q(axis_scores__score__isnull=False)),
            null_count=Count('axis_scores', filter=Q(axis_scores__score__isnull=True)),
        ).order_by('experience__source_kind', 'pk'), 25
    ).get_page(request.GET.get('page'))
    return _private(request, 'criteria_v2/pilot_dashboard_v213.html',
                    {'page': page, 'summary': summary, 'kind': kind,
                     'company_filter': company})


def _valid_analysis(analysis, story):
    exp = analysis.experience
    payload = analysis.raw_payload
    if (analysis.criteria_version != version_for(exp.source_kind) or
        analysis.source_content_sha256 != exp.content_sha256 or
        not isinstance(payload, dict) or
        payload.get('story_sha256') != story_digest(story) or
        exp.copyright_review == 'blocked' or
        exp.company_attribution_status == 'rejected' or
        exp.independence_status == 'duplicate'):
        return False
    expected = {a.key for a in axes_for(exp.source_kind)}
    rows = list(analysis.axis_scores.all())
    if len(rows) != 6 or {row.key for row in rows} != expected:
        return False
    for row in rows:
        if row.semantic_status != 'unreviewed':
            return False
        if row.score is None:
            if row.confidence != 0 or row.evidence not in ([], None):
                return False
        else:
            if (type(row.score) is not int or not 1 <= row.score <= 10 or
                type(row.confidence) is not int or not 70 <= row.confidence <= 100 or
                not isinstance(row.evidence, list) or not row.evidence or
                not all(isinstance(q, str) and 12 <= len(q) <= 450 and q in story
                            and not any(marker in q for marker in ('[email]', '[phone]', '[number]'))
                            for q in row.evidence)):
                return False
    return True


@never_cache
@require_GET
def detail(request, analysis_id):
    _authorize(request)
    analysis = get_object_or_404(
        _only_pilot().select_related('experience', 'experience__company')
        .prefetch_related('axis_scores'), pk=analysis_id)
    exp = analysis.experience
    story = story_from_experience(exp)
    integrity_ok = _valid_analysis(analysis, story)
    mapped = {row.key: row for row in analysis.axis_scores.all()}
    axes = [{'definition': axis, 'item': mapped.get(axis.key)}
            for axis in axes_for(exp.source_kind)]
    return _private(request, 'criteria_v2/pilot_detail_v213.html',
                    {'analysis': analysis, 'axes': axes,
                     'integrity_ok': integrity_ok,
                     'story': story if integrity_ok else '',
                     'number_scored': sum(item['item'] is not None and
                                          item['item'].score is not None for item in axes)})
