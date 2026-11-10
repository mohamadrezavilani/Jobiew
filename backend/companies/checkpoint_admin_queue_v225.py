"""Company-centered private checkpoint review queue rendered inside Django admin."""
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from criteria_v2.checkpoint_access_v218 import authorize_checkpoint
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.models import CriteriaAnalysis


@never_cache
@require_GET
def checkpoint_review_queue(request):
    authorize_checkpoint(request)
    if not request.user.has_perm('companies.view_company'):
        raise PermissionDenied('Company review permission required')
    q = request.GET.get('q', '').strip()[:90]
    records = CriteriaAnalysis.objects.filter(raw_payload__engine=ENGINE)
    if q:
        records = records.filter(experience__company__display_name__icontains=q)
    records = (records.values('experience__company_id', 'experience__company__display_name')
               .annotate(
                   total=Count('pk'),
                   pending=Count('pk', filter=Q(review_status='pilot_unverified')),
                   approved=Count('pk', filter=Q(review_status='approved')),
                   no_evidence=Count('pk', filter=Q(review_status='no_evaluable_scores')),
               ).order_by('-pending', 'experience__company__display_name',
                          'experience__company_id'))
    page = Paginator(records, 30).get_page(request.GET.get('page'))
    response = render(request, 'admin/companies/company/checkpoint_queue_v225.html', {
        'title': 'تأیید گروهی و انتشار امتیازهای شرکت‌ها',
        'page': page, 'q': q,
    })
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'no-referrer'
    return response
