"""Read-only, DEV-only company roll-up of *unverified* pilot proposals.

This page intentionally does NOT use company_public_sufficiency and does NOT
publish averages. All source authorizations stay pending/independent.
"""
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.http import Http404

from companies.models import Company
from experiences.models import PublicExperience
from .engine_v207 import story_from_experience
from .pilot_dashboard_v213 import _authorize, _private, _only_pilot, _valid_analysis
from .private_rollup_v216 import aggregate_pilot


@never_cache
@require_GET
def company_preview(request, pk):
    _authorize(request)
    company = get_object_or_404(Company, pk=pk)
    # Bounded private pilot page: fail closed rather than silently truncating.
    qs = (_only_pilot().filter(experience__company=company)
          .select_related('experience').prefetch_related('axis_scores')
          .order_by('experience_id', '-created_at', '-pk'))
    if qs.count() > 1000:
        raise Http404('Pilot page capacity exceeded; use bounded audit command')
    by_kind = {'work': [], 'interview': []}
    for run in qs:
        exp = run.experience
        if exp.source_kind not in by_kind:
            continue
        valid = _valid_analysis(run, story_from_experience(exp))
        dims = {r.key: r.score for r in run.axis_scores.all()} if valid else {}
        by_kind[exp.source_kind].append((exp.pk, valid, dims))
    results = {}
    for kind in ('work', 'interview'):
        results[kind] = aggregate_pilot(
            kind, total_experiences=PublicExperience.objects.filter(
                company=company, source_kind=kind).count(),
            candidates=by_kind[kind])
    return _private(request, 'criteria_v2/pilot_company_v216.html',
                    {'company': company, 'work': results['work'], 'interview': results['interview'], 'rollups': [results['work'], results['interview']]})
