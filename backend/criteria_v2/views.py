"""Separate company framework and staff re-review queue. No numeric ratings."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Subquery, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from urllib.parse import urlsplit
from companies.models import Company
from experiences.models import PublicExperience
from .models import CriteriaReviewEvent
from .registry import AXES, LABELS, VERSIONS, public_axes, version_for


def framework_context():
    return {'dual_criteria': public_axes(), 'dual_labels': LABELS,
            'dual_versions': VERSIONS, 'dual_scoring_active': False}


def staff_only(request, *, need_write=False):
    if not (request.user.is_authenticated and request.user.is_staff and
            request.user.has_perm('experiences.view_publicexperience')):
        raise PermissionDenied('Staff experience permission required')
    if need_write and not request.user.has_perm('criteria_v2.add_criteriareviewevent'):
        raise PermissionDenied('Review permission required')


def response_private(request, template, context):
    res = render(request, template, context)
    res['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    res['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return res


def pending_queryset(kind):
    if kind not in VERSIONS:
        raise ValueError('Unsupported scope')
    last = (CriteriaReviewEvent.objects.filter(
        experience_id=OuterRef('pk'), source_kind=kind,
        criteria_version=version_for(kind),
        source_content_sha256=OuterRef('content_sha256'),
    ).order_by('-created_at','-pk'))
    return PublicExperience.objects.filter(source_kind=kind).annotate(
        latest_scope_review=Subquery(last.values('decision')[:1])
    ).filter(
        Q(latest_scope_review__isnull=True) | Q(latest_scope_review='needs_revision')
    )


@never_cache
@require_GET
def private_company_framework(request, pk):
    staff_only(request)
    company = get_object_or_404(Company, pk=pk)
    counts = {kind: PublicExperience.objects.filter(company=company, source_kind=kind).count()
              for kind in VERSIONS}
    pendings = {kind: pending_queryset(kind).filter(company=company).count() for kind in VERSIONS}
    return response_private(request, 'criteria_v2/company_internal.html', {
        'company': company, 'counts': counts, 'pendings': pendings, **framework_context()})


@never_cache
@require_http_methods(['GET', 'POST'])
def review_queue(request):
    staff_only(request, need_write=request.method == 'POST')
    kind = request.GET.get('kind', 'work') if request.method == 'GET' else request.POST.get('kind', 'work')
    if kind not in VERSIONS:
        return HttpResponseBadRequest('Invalid experience type')
    if request.method == 'POST':
        record = request.POST.get('experience_id')
        verdict = request.POST.get('decision')
        note = (request.POST.get('note') or '').strip()
        suggested = (request.POST.get('suggested_kind') or '').strip()
        if not str(record).isdigit() or verdict not in {'confirmed','needs_revision','excluded'}:
            return HttpResponseBadRequest('Invalid review event')
        if suggested and suggested not in VERSIONS:
            return HttpResponseBadRequest('Invalid suggested kind')
        if suggested and (suggested == kind or verdict == 'confirmed'):
            return HttpResponseBadRequest('Inconsistent proposed kind')
        if verdict != 'confirmed' and len(note) < 8:
            return HttpResponseBadRequest('Provide a reason of at least eight characters')
        with transaction.atomic():
            exp = get_object_or_404(PublicExperience.objects.select_for_update(), pk=int(record), source_kind=kind)
            last = (CriteriaReviewEvent.objects.filter(
                experience=exp, source_content_sha256=exp.content_sha256,
                criteria_version=version_for(kind))
                .order_by('-created_at','-pk').first())
            if last and last.decision == 'confirmed' and verdict == 'confirmed':
                return HttpResponseBadRequest('Already confirmed; duplicate review not required')
            CriteriaReviewEvent.objects.create(
                experience=exp, reviewer=request.user, source_kind=kind,
                criteria_version=version_for(kind), source_content_sha256=exp.content_sha256,
                decision=verdict, suggested_kind=suggested, note=note)
        messages.success(request, 'وضعیت بازبینی نظر ثبت شد؛ هیچ نمره‌ای تغییر نکرد.')
        return redirect(f'{request.path}?kind={kind}')
    qs = pending_queryset(kind).select_related('company').order_by('imported_at','pk')
    page = Paginator(qs, 40).get_page(request.GET.get('page'))
    for exp in page.object_list:
        try:
            u = urlsplit(exp.source_url or '')
            exp.safe_source_url = exp.source_url if u.scheme in ('http', 'https') and u.hostname and not u.username and not u.password else ''
        except (TypeError, ValueError):
            exp.safe_source_url = ''
    counts = {x: pending_queryset(x).count() for x in VERSIONS}
    return response_private(request, 'criteria_v2/review_queue.html', {
        'kind':kind, 'page':page, 'counts':counts, 'axes':AXES[kind],
        'kind_label':LABELS[kind], 'version':version_for(kind),
        'can_review':request.user.has_perm('criteria_v2.add_criteriareviewevent'),
    })

@never_cache
@require_GET
def archived_legacy_report(request):
    """Former five-axis analytics/comparison URLs no longer display old ratings."""
    staff_only(request)
    return response_private(request, 'criteria_v2/archived_report.html', {})
