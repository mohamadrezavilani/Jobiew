"""Staff-only read-only research pentagon. Public company detail remains score-free."""
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from assessments.five_criteria_company_v7 import build_company_research_preview
from .models import Company


@never_cache
@require_GET
def staff_five_criteria_preview(request, pk):
    if not (request.user.is_authenticated and request.user.is_staff and
            request.user.has_perm('companies.view_company') and
            request.user.has_perm('assessments.view_aiassessment')):
        raise PermissionDenied('Not authorized for internal research preview')
    company = get_object_or_404(Company, pk=pk)
    result = build_company_research_preview(company)
    response = render(request, 'companies/research_five_criteria_v7.html',
                      {'company': company, 'preview': result})
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response
