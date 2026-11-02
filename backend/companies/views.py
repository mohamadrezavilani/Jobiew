"""Public read-only views. No source bodies and no unapproved scores are exposed."""
from django.core.paginator import Paginator
from django.db.models import Q
from urllib.parse import urlsplit
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from .models import Company


def index(request):
    qs=Company.objects.order_by('display_name','id')
    q=request.GET.get('q','').strip()[:100]
    if q:qs=qs.filter(display_name__icontains=q)
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    return render(request,'companies/index.html',{'page':page,'q':q})



def _public_experience_queryset(company):
    """Only public *metadata and links*, never copied source body or unapproved AI.

    A blocked source or rejected attribution is never included. Source titles, raw
    comments and all pros/cons stay private even if the URL appears publicly.
    """
    from experiences.models import PublicExperience
    return (PublicExperience.objects.filter(company=company)
            .exclude(copyright_review='blocked')
            .exclude(company_attribution_status='rejected')
            .exclude(independence_status='duplicate')
            .exclude(source_url=''))


def _safe_source_url(value):
    """Protect the public href from unexpected URL schemes."""
    try:
        url = urlsplit(value)
        if url.scheme.lower() in ('http', 'https') and url.hostname:
            return value
    except (ValueError, TypeError):
        pass
    return None



def detail(request, pk):
    c = get_object_or_404(Company, pk=pk)
    from assessments.models import DIMENSIONS
    from assessments.publication_workflow_v104 import public_company_assessments

    # Existing approved five-dimension AI display stays unchanged.
    published = public_company_assessments(c)
    tab = request.GET.get('tab', 'ai')
    if tab not in ('ai', 'work', 'interview'):
        tab = 'ai'

    available = _public_experience_queryset(c)
    work_count = available.filter(source_kind='work').count()
    interview_count = available.filter(source_kind='interview').count()
    context = {'company': c, 'five_criteria': DIMENSIONS,
               'published_ai': published, 'active_tab': tab,
               'work_count': work_count, 'interview_count': interview_count}

    if tab in ('work', 'interview'):
        term = request.GET.get('q', '').strip()[:100]
        experiences = available.filter(source_kind=tab)
        if term:
            experiences = experiences.filter(
                Q(job_title__icontains=term) | Q(title__icontains=term))
        # Import order is deterministic; the source Jalali date is not sortable.
        experiences = experiences.order_by('-imported_at', '-pk').values(
            'id', 'job_title', 'published_jalali', 'source_url', 'source_site')
        page_obj = Paginator(experiences, 12).get_page(request.GET.get('page'))
        public_cards = [
            {'id': row['id'], 'job_title': row['job_title'],
             'date': row['published_jalali'],
             'source_site': row['source_site'],
             'source_url': _safe_source_url(row['source_url'])}
            for row in page_obj.object_list
        ]
        context.update({'experience_query': term, 'experience_page': page_obj,
                        'experience_cards': public_cards})

    return render(request, 'companies/detail.html', context)


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
