"""One company, one actionable admin workflow for existing GPT-6 checkpoints.

Read-only status hub. Each irreversible action still uses the existing
permission/CSRF/evidence-protected form; no validation or review gates bypassed.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from companies.models import Company
from companies.map_visibility_v232 import company_map_status
from criteria_v2.checkpoint_access_v218 import authorize_checkpoint
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.company_release_v224 import publication_candidates
from criteria_v2.models import CriteriaAnalysis
from criteria_v2.publication_state_v231 import company_publication_state


def company_workflow(admin_view, request, object_id):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    authorize_checkpoint(request)
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied
    summary = (CriteriaAnalysis.objects.filter(
        experience__company=company, raw_payload__engine=ENGINE)
        .aggregate(
            imported=Count('pk'),
            pending=Count('pk', filter=Q(review_status='pilot_unverified')),
            reviewed=Count('pk', filter=Q(
                review_status__in=('approved', 'no_evaluable_scores'))),
            numeric=Count('pk', filter=Q(review_status='approved')),
            abstained=Count('pk', filter=Q(review_status='no_evaluable_scores')),
        ))
    from experiences.models import PublicExperience
    total_experiences = PublicExperience.objects.filter(company=company).count()
    proofs, blockers = publication_candidates(company)
    public = company_publication_state(company)
    location = company_map_status(company)
    identity_ready = company.identity_status == 'verified' and company.tech_status == 'verified'
    ordinary_ready = not any(blockers[f + '_missing'] for f in (
        'attribution', 'independence', 'classification'))
    rights_ready = blockers['copyright_missing'] == 0
    needs_score_review = bool(summary['pending'])
    current_snapshot = bool(
        public['release'] and public['release'].decision == 'published'
        and public['release'].approved_runs == proofs)
    can_publish = bool(proofs) and not current_snapshot
    if not summary['imported']:
        next_step = 'ingestion'
    elif needs_score_review:
        next_step = 'scores'
    elif not identity_ready:
        next_step = 'identity'
    elif not ordinary_ready or not rights_ready:
        next_step = 'sources'
    elif can_publish:
        next_step = 'release'
    else:
        next_step = 'complete'
    url = lambda name: reverse('admin:companies_company_' + name, args=[company.pk])
    ctx = {
        **admin_view.admin_site.each_context(request),
        'title': 'میز کار ' + company.display_name,
        'opts': admin_view.model._meta,
        'company': company,
        'total_experiences': total_experiences,
        'summary': summary,
        'blockers': blockers,
        'public_state': public,
        'map_state': location,
        'identity_ready': identity_ready,
        'ordinary_ready': ordinary_ready,
        'rights_ready': rights_ready,
        'next_step': next_step,
        'can_publish': can_publish,
        'current_snapshot': current_snapshot,
        'experiences_url': url('experiences'),
        'bulk_url': url('checkpoint_bulk'),
        'verify_url': url('checkpoint_verify'),
        'sources_url': url('checkpoint_sources'),
        'release_url': url('checkpoint_release'),
        'map_review_url': url('review') + '#map-visibility',
        'public_url': reverse('company-detail', args=[company.pk]) + '?tab=ai#dual-criteria',
    }
    response = TemplateResponse(
        request, 'admin/companies/company/workflow_v233.html', ctx)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'same-origin'
    return response
