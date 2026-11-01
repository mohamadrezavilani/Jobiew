"""Private side-by-side comparison of unreviewed five-criterion company data.

No public rating or ranking is computed. Read-only and staff-permission scoped.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from assessments.five_criteria_company_v7 import build_company_research_preview, LABELS
from assessments.five_criteria_contract import KEYS
from .models import Company

MAX_COMPANIES = 5
SEARCH_LIMIT = 30


def _private_response(request, template, context):
    response = render(request, template, context)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


@never_cache
@require_GET
def staff_five_criteria_compare(request):
    if not (request.user.is_authenticated and request.user.is_staff and
            request.user.has_perm('companies.view_company') and
            request.user.has_perm('assessments.view_aiassessment')):
        raise PermissionDenied('Not authorized for internal five-criteria comparison')

    chosen_ids = request.GET.getlist('company')
    if (len(chosen_ids) > MAX_COMPANIES or
            len(set(chosen_ids)) != len(chosen_ids) or
            any(not x or len(x) > 24 for x in chosen_ids)):
        return HttpResponseBadRequest('حداکثر ۵ شناسه شرکت یکتا مجاز است.')

    companies = {str(c.pk): c for c in Company.objects.filter(pk__in=chosen_ids)}
    if len(companies) != len(chosen_ids):
        return HttpResponseBadRequest('شناسه شرکت انتخاب‌شده معتبر نیست.')
    selected = [companies[pk] for pk in chosen_ids]

    q = request.GET.get('q', '').strip()[:100]
    candidates = Company.objects.all()
    if q:
        candidates = candidates.filter(
            Q(display_name__icontains=q) | Q(source_name__icontains=q) | Q(pk__icontains=q)
        )
    if chosen_ids:
        candidates = candidates.exclude(pk__in=chosen_ids)
    candidates = list(candidates.order_by('display_name', 'pk')[:SEARCH_LIMIT])

    entries = []
    for company in selected:
        preview = build_company_research_preview(company)
        criteria = preview['criteria']
        entries.append({
            'company': company,
            'unique_experiences': preview['unique_experiences_in_scope'],
            'scored_criteria': sum(x['mean_provisional'] is not None for x in criteria),
            'criteria': criteria,
        })

    matrix = []
    for index, key in enumerate(KEYS):
        cells = []
        for entry in entries:
            dimension = entry['criteria'][index]
            assert dimension['key'] == key
            cells.append({
                'score': dimension['mean_provisional'],
                'n': dimension['n_provisional_used'],
                'abstentions': dimension['n_provisional_abstentions'],
            })
        matrix.append({'key': key, 'label': LABELS[key], 'cells': cells})

    # Non-sensitive visualization payload: name, aggregate, and sample count only.
    plot_data = [
        {'id': str(entry['company'].pk),
         'name': entry['company'].display_name,
         'criteria': [
             {'label': dim['label'], 'score': dim['mean_provisional'],
              'n': dim['n_provisional_used']}
             for dim in entry['criteria']
         ]}
        for entry in entries
    ]

    return _private_response(
        request, 'companies/research_five_criteria_compare_v12.html',
        {'q': q, 'selected': selected, 'candidates': candidates, 'entries': entries,
         'matrix': matrix, 'plot_data': plot_data, 'ready': len(entries) >= 2,
         'max_companies': MAX_COMPANIES},
    )
