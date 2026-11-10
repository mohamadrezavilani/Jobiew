"""Explicit per-company publication of a fixed set of private, human-reviewed scores.

A release never changes source rights, experience text, AI ratings or feature
flags. Each public request checks independently recorded source provenance and
the immutable six-axis receipt again. New checkpoint imports are not added to
an earlier publication decision.
"""
import hashlib
import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie

from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent
from .checkpoint_access_v218 import authorize_checkpoint
from .checkpoint_contract_v218 import ENGINE
from .checkpoint_receipt_v222 import approved_checkpoint_digest, checkpoint_release_ready
from .models import CriteriaAnalysis, CriteriaReviewEvent, CriteriaCompanyReleaseEvent
from .pilot_dashboard_v213 import _private
from .registry import version_for

MAX_RELEASE_RUNS = 1000


def _latest_rights(exp):
    required = (('copyright', 'approved', exp.copyright_review),
                ('attribution', 'verified', exp.company_attribution_status),
                ('independence', 'verified', exp.independence_status))
    for field, expected, status in required:
        if status != expected:
            return False
        event = (ExperienceReviewEvent.objects.filter(experience_id=exp.pk, review_field=field)
                 .order_by('-created_at', '-pk').first())
        if (event is None or event.decision != expected or
                not isinstance(event.evidence_url, str) or not event.evidence_url.strip()):
            return False
    return True


def _current_classification(exp):
    event = (CriteriaReviewEvent.objects.filter(
        experience_id=exp.pk, source_kind=exp.source_kind,
        criteria_version=version_for(exp.source_kind))
        .order_by('-created_at', '-pk').first())
    return (event is not None and event.decision == 'confirmed'
            and event.source_content_sha256 == exp.content_sha256)


def publication_candidates(company):
    """Return (evidence-bound proof map, progress counters).

    Do not silently approve or falsify missing source licences. The only
    required inputs are existing audited decisions and unchanged AI scores.
    """
    qs = (CriteriaAnalysis.objects.filter(experience__company=company,
        raw_payload__engine=ENGINE)
        .select_related('experience', 'experience__company')
        .prefetch_related('axis_scores')
        .order_by('experience_id', '-created_at', '-pk'))
    seen = set()
    proofs = {}
    status = {'pending': 0, 'human_reviewed': 0, 'cleared': 0,
              'blocked_provenance': 0, 'invalid_or_changed': 0,
              'company_verified': (company.identity_status == 'verified'
                                   and company.tech_status == 'verified')}
    for run in qs:
        exp = run.experience
        if exp.pk in seen:
            continue
        seen.add(exp.pk)
        if len(seen) > MAX_RELEASE_RUNS:
            raise ValueError('COMPANY_RELEASE_CAP_EXCEEDED')
        if run.review_status == 'pilot_unverified':
            status['pending'] += 1
            continue
        if run.review_status == 'no_evaluable_scores':
            status['human_reviewed'] += 1
            continue
        if run.review_status != 'approved':
            status['invalid_or_changed'] += 1
            continue
        status['human_reviewed'] += 1
        if (not status['company_verified'] or not _latest_rights(exp) or
                not _current_classification(exp)):
            status['blocked_provenance'] += 1
            continue
        if not checkpoint_release_ready(run):
            status['invalid_or_changed'] += 1
            continue
        digest = approved_checkpoint_digest(run)
        if digest is None:
            status['invalid_or_changed'] += 1
            continue
        proofs[str(run.pk)] = digest
        status['cleared'] += 1
    return proofs, status


def effective_release_proofs(company):
    event = CriteriaCompanyReleaseEvent.objects.filter(company=company).first()
    if event is None or event.decision != 'published' or not isinstance(event.approved_runs, dict):
        return {}
    return event.approved_runs


def _token(company, proofs, status):
    material = [company.pk, company.identity_status, company.tech_status,
                sorted(proofs.items()), status]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode('utf8')).hexdigest()


@never_cache
@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def company_release(request, pk):
    authorize_checkpoint(request)
    if not request.user.has_perm('criteria_v2.add_criteriacompanyreleaseevent'):
        raise PermissionDenied('Company publication permission required')
    company = get_object_or_404(Company, pk=pk)
    try:
        proofs, stats = publication_candidates(company)
    except ValueError:
        raise Http404('Company exceeds release review safety limit')
    token = _token(company, proofs, stats)
    current = CriteriaCompanyReleaseEvent.objects.filter(company=company).first()
    if request.method == 'GET':
        import os
        response = _private(request, 'criteria_v2/company_release_v224.html', {
            'company': company, 'stats': stats, 'eligible_count': len(proofs),
            'admin_mode': request.resolver_match.url_name == 'companies_company_checkpoint_release',
            'current': current, 'token': token,
            'public_enabled': (os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED') == '1'
                and os.environ.get('JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED') == '1'
                and os.environ.get('JOBIEW_COMPANY_RELEASE_ONLY_ENABLED') == '1'),
        })
        # Keep referrers on same-origin form submissions only; the current
        # 'no-referrer' policy breaks Django HTTPS CSRF on browsers omitting Origin.
        response['Referrer-Policy'] = 'same-origin'
        return response
    action = request.POST.get('action')
    note = (request.POST.get('note') or '').strip()
    if (action not in ('published', 'held') or not 20 <= len(note) <= 1200 or
            request.POST.get('snapshot') != token or
            request.POST.get('confirm_public') != 'yes'):
        return HttpResponse('RELEASE_CONFIRMATION_REQUIRED_OR_STALE', status=400)
    if action == 'published' and request.POST.get('confirm_rights') != 'yes':
        return HttpResponse('SOURCE_RIGHTS_CONFIRMATION_REQUIRED', status=400)
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=pk)
        list(PublicExperience.objects.select_for_update().filter(company=company)
             .order_by('pk').values_list('pk', flat=True))
        try:
            confirmed, new_stats = publication_candidates(company)
        except ValueError:
            return HttpResponse('COMPANY_RELEASE_CAP_EXCEEDED', status=409)
        if _token(company, confirmed, new_stats) != token:
            return HttpResponse('STALE_COMPANY_RELEASE_SNAPSHOT', status=409)
        if action == 'published' and not confirmed:
            return HttpResponse('NO_RIGHTS_CLEARED_REVIEWED_SCORES_TO_PUBLISH', status=409)
        CriteriaCompanyReleaseEvent.objects.create(
            company=company, reviewer=request.user, decision=action,
            approved_runs=confirmed if action == 'published' else {}, note=note)
    messages.success(request, ('انتشار امتیازهای تأییدشدهٔ این شرکت ثبت شد. '
        if action == 'published' else 'انتشار امتیازهای این شرکت متوقف شد. ') +
        'نمایش عمومی فقط با گیت‌های جداگانه و بازبینی زندهٔ مجوز منبع ممکن است.')
    if request.resolver_match.url_name == 'companies_company_checkpoint_release':
        return redirect('admin:companies_company_checkpoint_release', object_id=pk)
    return redirect('dual-company-release-v224', pk=pk)
