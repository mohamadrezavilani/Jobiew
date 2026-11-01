"""Staff-only analytical browsing, on-demand PostgreSQL read model (no writes)."""
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from assessments.models import AiAssessment, AiDimension, FIVE_CRITERIA_VERSION
from assessments.five_criteria_company_v7 import build_company_research_preview
from assessments.five_criteria_analysis_v13 import analyze_provisional_criteria
from .models import Company


@never_cache
@require_GET
def staff_five_criteria_analytics(request):
    if not (request.user.is_authenticated and request.user.is_staff and
            request.user.has_perm('companies.view_company') and
            request.user.has_perm('assessments.view_aiassessment')):
        raise PermissionDenied('Private research report permission required')

    q=request.GET.get('q','').strip()[:100]
    scope=AiAssessment.objects.filter(criteria_version=FIVE_CRITERIA_VERSION,
                                      experience__source_kind='work')
    companies=Company.objects.filter(experiences__ai_assessments__criteria_version=FIVE_CRITERIA_VERSION,
                                     experiences__source_kind='work').distinct()
    if q:
        companies=companies.filter(Q(display_name__icontains=q) |
                                   Q(source_name__icontains=q) | Q(pk__icontains=q))
    companies=companies.order_by('display_name','pk')
    page=Paginator(companies,20).get_page(request.GET.get('page'))
    entries=[]
    for company in page.object_list:
        preview=build_company_research_preview(company)
        summary=analyze_provisional_criteria(preview['criteria'])
        entries.append({'company':company,'preview':preview,'analysis':summary})
    # Overall totals are not scores or rankings; distinct prevents counting multiple runs twice.
    response=render(request,'companies/research_five_criteria_analytics_v13.html',{
        'q':q,'page':page,'entries':entries,
        'total_companies':Company.objects.filter(experiences__ai_assessments__criteria_version=FIVE_CRITERIA_VERSION,
                                                  experiences__source_kind='work').values('pk').distinct().count(),
        'total_experiences':scope.values('experience_id').distinct().count(),
        'total_provisional_scores':AiDimension.objects.filter(assessment__criteria_version=FIVE_CRITERIA_VERSION,
            assessment__experience__source_kind='work',score__isnull=False).count(),
        'publication_status':'NOT_APPROVED_FOR_PUBLICATION',
    })
    response['Cache-Control']='private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag']='noindex, nofollow, noarchive'
    return response
