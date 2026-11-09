"""Staff-only, DEBUG-only preview of unverified checkpoint proposals.

Not a public ranking, not independent semantic validation, no writes and no
transition to approved. Author source texts remain private.
"""
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from companies.models import Company
from experiences.models import PublicExperience
from .checkpoint_contract_v218 import ENGINE, STATUS
from .engine_v207 import story_from_experience
from .models import CriteriaAnalysis
from .pilot_dashboard_v213 import _private, _valid_analysis
from .checkpoint_access_v218 import authorize_checkpoint
from .private_rollup_v216 import aggregate_pilot
from .registry import axes_for


def _staged():
    return CriteriaAnalysis.objects.filter(
        review_status=STATUS, raw_payload__engine=ENGINE,
    )


@never_cache
@require_GET
def index(request):
    authorize_checkpoint(request)
    qs = (_staged().values('experience__company_id',
                          'experience__company__display_name')
          .annotate(experiences=Count('experience_id', distinct=True))
          .order_by('-experiences', 'experience__company_id'))
    page = Paginator(qs, 30).get_page(request.GET.get('page'))
    return _private(request, 'criteria_v2/checkpoint_index_v218.html',
                    {'page': page, 'staged': _staged().count()})


@never_cache
@require_GET
def company_preview(request, pk):
    authorize_checkpoint(request)
    company = get_object_or_404(Company, pk=pk)
    qs = (_staged().filter(experience__company=company)
          .select_related('experience').prefetch_related('axis_scores')
          .order_by('experience_id', '-created_at', '-pk'))
    if qs.count() > 5000:
        raise Http404('Private inspection capacity exceeded')
    items = {'work': [], 'interview': []}
    inspection_cases = []
    seen = set()
    for run in qs:
        exp = run.experience
        if exp.source_kind not in items:
            continue
        valid = _valid_analysis(run, story_from_experience(exp))
        dims = {row.key: row.score for row in run.axis_scores.all()} if valid else {}
        items[exp.source_kind].append((exp.pk, valid, dims))
        # Show only the newest run for each source, never imply two votes.
        if exp.pk not in seen and len(inspection_cases) < 100:
            inspection_cases.append({'id': run.pk, 'source_id': exp.pk,
                                     'kind': exp.source_kind, 'valid': valid,
                                     'numeric': sum(x is not None for x in dims.values())})
        seen.add(exp.pk)
    results = {}
    for kind in ('work', 'interview'):
        total = PublicExperience.objects.filter(company=company, source_kind=kind).count()
        results[kind] = aggregate_pilot(kind, total_experiences=total,
                                        candidates=items[kind])
    return _private(request, 'criteria_v2/checkpoint_company_v218.html',
                    {'company': company, 'rollups': [results['work'], results['interview']],
                     'work': results['work'], 'interview': results['interview'],
                     'inspection_cases': inspection_cases})


@never_cache
@require_GET
def detail(request, analysis_id):
    authorize_checkpoint(request)
    analysis = get_object_or_404(
        _staged().select_related('experience', 'experience__company')
        .prefetch_related('axis_scores'), pk=analysis_id)
    exp = analysis.experience
    story = story_from_experience(exp)
    valid = _valid_analysis(analysis, story)
    data = {row.key: row for row in analysis.axis_scores.all()} if valid else {}
    axes = [{'definition': axis, 'item': data.get(axis.key)}
            for axis in axes_for(exp.source_kind)]
    return _private(request, 'criteria_v2/checkpoint_detail_v218.html',
                    {'analysis': analysis, 'integrity_ok': valid,
                     'axes': axes, 'story': story if valid else ''})
