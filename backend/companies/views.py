"""Public read-only views. No source bodies and no unapproved scores are exposed."""
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from .models import Company


def index(request):
    qs=Company.objects.order_by('display_name','id')
    q=request.GET.get('q','').strip()[:100]
    if q:qs=qs.filter(display_name__icontains=q)
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    return render(request,'companies/index.html',{'page':page,'q':q})


def detail(request, pk):
    c=get_object_or_404(Company, pk=pk)
    from assessments.models import DIMENSIONS
    # Deliberately no experimental AI score is leaked into public HTML.
    # A separate independently-approved publication endpoint is required.
    return render(request,'companies/detail.html',{'company':c, 'five_criteria': DIMENSIONS})


def company_map(request):
    """Prototype map; blank until independent editorial verification is complete."""
    return render(request, 'companies/map.html')


def approved_geojson(request):
    """Never publish unverified, stale or directly injected coordinates."""
    from django.db.models import OuterRef, Subquery, F
    from locations.models import CompanyLocation, CompanyLocationReviewEvent

    latest = CompanyLocationReviewEvent.objects.filter(company_id=OuterRef('company_id')).order_by('-created_at', '-pk')
    rows = CompanyLocation.objects.select_related('company').annotate(
        reviewed_decision=Subquery(latest.values('decision')[:1]),
        reviewed_latitude=Subquery(latest.values('latitude')[:1]),
        reviewed_longitude=Subquery(latest.values('longitude')[:1]),
        reviewed_evidence_url=Subquery(latest.values('evidence_url')[:1]),
    ).filter(
        verification_status='verified', verified_at__isnull=False,
        company__identity_status='verified', company__tech_status='verified',
        company__tehran_status='verified',
        latitude__isnull=False, longitude__isnull=False,
        reviewed_decision='verified', reviewed_latitude=F('latitude'),
        reviewed_longitude=F('longitude'), reviewed_evidence_url=F('evidence_url'),
    ).exclude(evidence_url='')
    features = [
        {'type': 'Feature',
         'geometry': {'type': 'Point', 'coordinates': [float(row.longitude), float(row.latitude)]},
         'properties': {'company_id': row.company_id, 'name': row.company.display_name}}
        for row in rows
    ]
    return JsonResponse({'type': 'FeatureCollection', 'features': features})
