"""Human-reviewed, company-scoped provenance checklist for existing GPT-6 scores.

This is NOT a licence inference or an automatic approval mechanism. Each
explicitly selected experience receives separate append-only source/class
events, with a traceable human reviewer and stated evidence. No publication
decision is ever made by this view.
"""
import hashlib
import json
from urllib.parse import urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from companies.models import Company
from experiences.models import PublicExperience, ExperienceReviewEvent
from criteria_v2.checkpoint_access_v218 import authorize_checkpoint
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.checkpoint_receipt_v222 import checkpoint_release_ready
from criteria_v2.company_release_v224 import (
    _current_classification, _missing_source_rights,
)
from criteria_v2.models import CriteriaAnalysis, CriteriaReviewEvent
from criteria_v2.publication_state_v231 import company_publication_state
from criteria_v2.registry import version_for

MAX_CASES = 1000

# A single, human-attested action covers the three non-copyright decisions.
# Reviewers can narrow its scope without clicking three independent checkboxes.
STANDARD_SCOPES = {
    'standard': ('classification', 'attribution', 'independence'),
    'classification': ('classification',),
    'attribution': ('attribution',),
    'independence': ('independence',),
}
FIELDS = ('copyright', 'attribution', 'independence', 'classification')
LABELS = {
    'copyright': 'مجوز استفاده از منبع برای انتشار امتیاز',
    'attribution': 'انتساب تجربه به شرکت',
    'independence': 'استقلال و غیرتکراری بودن تجربه',
    'classification': 'نوع تجربه: کاری یا مصاحبه',
}
SOURCE_DECISIONS = {
    'copyright': 'approved',
    'attribution': 'verified',
    'independence': 'verified',
}
EXPLICIT_BLOCKS = {
    'copyright': 'blocked',
    'attribution': 'rejected',
    'independence': 'duplicate',
}


def _https_document(raw):
    if not isinstance(raw, str) or len(raw) > 1500:
        return False
    try:
        parts = urlsplit(raw)
        return (parts.scheme == 'https' and bool(parts.hostname)
                and not parts.username and not parts.password
                and parts.hostname.lower() not in ('localhost', '127.0.0.1', '::1'))
    except (TypeError, ValueError):
        return False


def _safe_source_url(raw):
    try:
        parts = urlsplit(raw or '')
        if (parts.scheme in ('https', 'http') and parts.hostname
                and not parts.username and not parts.password):
            return raw
    except (ValueError, TypeError):
        pass
    return ''


def _latest_event(exp, key):
    return (ExperienceReviewEvent.objects.filter(
        experience_id=exp.pk, review_field=key
    ).order_by('-created_at', '-pk').first())


def _rows(company):
    runs = (CriteriaAnalysis.objects.filter(
        experience__company=company, raw_payload__engine=ENGINE,
        review_status__in=('approved', 'no_evaluable_scores'))
        .select_related('experience').prefetch_related('axis_scores')
        .order_by('experience_id', '-created_at', '-pk'))
    rows = []
    seen = set()
    for run in runs:
        exp = run.experience
        if exp.pk in seen:
            continue
        seen.add(exp.pk)
        if len(seen) > MAX_CASES:
            raise ValueError('COMPANY_PROVENANCE_REVIEW_CAP_EXCEEDED')
        if run.review_status != 'approved':
            continue
        if not checkpoint_release_ready(run):
            continue
        gaps = _missing_source_rights(exp)
        if not _current_classification(exp):
            gaps.append('classification')
        if not gaps:
            continue
        events = {field: _latest_event(exp, field)
                  for field in SOURCE_DECISIONS}
        explicitly_blocked = any(
            getattr(exp, dict(copyright='copyright_review',
                attribution='company_attribution_status',
                independence='independence_status')[field]) == decision or
            (events[field] is not None and events[field].decision == decision)
            for field, decision in EXPLICIT_BLOCKS.items()
        )
        rows.append({
            'exp': exp, 'run': run,
            'gaps': gaps, 'gap_labels': [LABELS[x] for x in gaps],
            'eligible': not explicitly_blocked,
            'blocked': explicitly_blocked,
            'source_href': _safe_source_url(exp.source_url),
        })
    return rows


def _snapshot(company, rows):
    payload = {
        'company': company.pk,
        'company_status': [company.identity_status, company.tech_status],
        'cases': [
            [row['exp'].pk, row['exp'].company_id,
             row['exp'].content_sha256, row['exp'].source_kind,
             row['exp'].source_url, row['exp'].source_site,
             row['run'].pk, row['run'].run_id, row['run'].review_status,
             row['gaps'], row['eligible'],
             list(ExperienceReviewEvent.objects.filter(
                 experience=row['exp']
             ).order_by('-created_at', '-pk').values_list('pk', 'review_field', 'decision')),
             list(CriteriaReviewEvent.objects.filter(
                 experience=row['exp']
             ).order_by('-created_at', '-pk').values_list('pk', 'decision')),
            ] for row in rows
        ],
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str
    ).encode('utf-8')).hexdigest()


def _valid_selected_ids(raw):
    if (not raw or len(raw) > MAX_CASES or len(raw) != len(set(raw))
            or any(not text.isascii() or not text.isdecimal() for text in raw)):
        return None
    return {int(item) for item in raw}


def provenance_review(admin_view, request, object_id):
    """Admin-wrapped (CSRF enabled), HTTPS-only company source reviews."""
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    authorize_checkpoint(request)
    if (not request.user.has_perm('companies.view_company')
            or not request.user.has_perm('experiences.add_experiencereviewevent')
            or not request.user.has_perm('criteria_v2.add_criteriareviewevent')):
        raise PermissionDenied('Separate source and classification reviewer rights required')
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied('Company scope denied')
    try:
        rows = _rows(company)
    except ValueError:
        raise Http404('Review batch too large')
    snapshot = _snapshot(company, rows)

    def review_page(error='', status=200):
        # The default selects reviewable rows, not factual/legal attestations.
        # POST errors preserve the user's actual selected IDs and draft fields.
        if request.method == 'GET':
            selected_ids = {row['exp'].pk for row in rows if row['eligible']}
        else:
            selected_ids = set()
            for raw in request.POST.getlist('selected'):
                if raw.isascii() and raw.isdecimal():
                    selected_ids.add(int(raw))
        normal_remaining = sum(
            any(gap in STANDARD_SCOPES['standard'] for gap in row['gaps'])
            for row in rows if row['eligible'])
        rights_remaining = sum(
            'copyright' in row['gaps'] for row in rows if row['eligible'])
        public_state = company_publication_state(company)
        ctx = {
            **admin_view.admin_site.each_context(request),
            'title': 'بررسی گروهی مدارک: ' + company.display_name,
            'company': company, 'rows': rows, 'snapshot': snapshot,
            'opts': admin_view.model._meta,
            'release_url': reverse(
                'admin:companies_company_checkpoint_release', args=[company.pk]),
            'bulk_url': reverse(
                'admin:companies_company_checkpoint_bulk', args=[company.pk]),
            'labels': LABELS,
            'available': sum(row['eligible'] for row in rows),
            'normal_remaining': normal_remaining,
            'rights_remaining': rights_remaining,
            'only_rights_left': normal_remaining == 0 and rights_remaining > 0,
            'public_state': public_state,
            'selected_ids': selected_ids,
            'error': error,
            'note_value': (request.POST.get('note', '') if request.method == 'POST' else ''),
            'rights_document_url': (request.POST.get('rights_document_url', '')
                                    if request.method == 'POST' else ''),
            'scope_value': request.POST.get('scope', 'standard'),
            'rights_open': request.POST.get('action') == 'rights',
        }
        response = TemplateResponse(
            request, 'admin/companies/company/provenance_review_v228.html',
            ctx, status=status)
        response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response['Referrer-Policy'] = 'same-origin'
        return response

    if request.method == 'GET':
        return review_page()

    selected = _valid_selected_ids(request.POST.getlist('selected'))
    action = request.POST.get('action', '')
    scope = request.POST.get('scope', 'standard')
    note = (request.POST.get('note') or '').strip()
    rights_doc = (request.POST.get('rights_document_url') or '').strip()
    if request.POST.get('snapshot') != snapshot:
        return review_page(
            'فهرست تجربه‌ها در این فاصله تغییر کرده است؛ صفحه را تازه کن و دوباره بررسی کن.',
            status=409)
    if selected is None:
        return review_page(
            'هیچ تجربه‌ای انتخاب نشده است. حداقل یک مورد بررسی‌شده را انتخاب کن.',
            status=400)
    if request.POST.get('confirm_manual') != 'yes':
        return review_page(
            'برای ثبت، باید صریحاً تأیید کنی همهٔ موارد انتخابی را شخصاً بررسی کرده‌ای.',
            status=400)
    if len(note) > 1200:
        return review_page('توضیح اختیاری باید کمتر از ۱۲۰۰ نویسه باشد.', status=400)
    if action == 'standard':
        checks = STANDARD_SCOPES.get(scope)
        if checks is None:
            return review_page('نوع بررسی انتخاب‌شده معتبر نیست.', status=400)
    elif action == 'rights':
        checks = ('copyright',)
        if not _https_document(rights_doc):
            return review_page(
                'برای ثبت مجوز انتشار، لینک HTTPS سند واقعی مجوز لازم است. '
                'اگر مجوزی نداری، از دکمهٔ «ثبت بررسی‌های عادی (بدون مجوز)» استفاده کن.',
                status=400)
    else:
        return review_page(
            'یکی از دو دکمهٔ ثبت بررسی عادی یا ثبت مجوز مستند را انتخاب کن.',
            status=400)
    rationale = (note if note else
        'بازبین با تأیید صریح، بررسی انسانی موارد انتخاب‌شده را '
        'در محدودهٔ تصمیم‌های ثبت‌شده اعلام کرده است.')
    with transaction.atomic():
        company = Company.objects.select_for_update().get(pk=company.pk)
        list(PublicExperience.objects.select_for_update().filter(
            company=company).order_by('pk').values_list('pk', flat=True))
        try:
            current = _rows(company)
        except ValueError:
            return HttpResponse('REVIEW_BATCH_TOO_LARGE', status=409)
        if _snapshot(company, current) != snapshot:
            return review_page('وضعیت تجربه‌ها عوض شده است؛ صفحه را تازه کن.', status=409)
        index = {row['exp'].pk: row for row in current}
        if (not selected.issubset(index)
                or any(not index[exp_id]['eligible'] for exp_id in selected)):
            return review_page('یکی از تجربه‌های انتخابی متعلق به شرکت نیست یا قبلاً رد شده است.', status=400)
        selected_rows = [index[exp_id] for exp_id in sorted(selected)]
        if (any(not row['source_href'] for row in selected_rows)
                and any(check != 'classification' for check in checks)):
            return review_page('برای بررسی انتساب یا استقلال، لینک معتبر منبع هر تجربه لازم است.', status=400)
        if 'copyright' in checks:
            source_sites = {row['exp'].source_site for row in selected_rows}
            if len(source_sites) != 1:
                return review_page('هر بار مجوز یک سایت منبع را بررسی کن؛ موارد مربوط به سایت‌های دیگر را جدا ثبت کن.', status=400)
            if any(rights_doc == row['exp'].source_url for row in selected_rows):
                return review_page('آدرس خود تجربه، سند مجوز نیست. لینک سند مجوز مستقل را وارد کن.', status=400)

        created = 0
        for row in selected_rows:
            exp = row['exp']
            for key in checks:
                if key not in row['gaps']:
                    continue
                if key == 'classification':
                    CriteriaReviewEvent.objects.create(
                        experience=exp, reviewer=request.user,
                        source_kind=exp.source_kind,
                        criteria_version=version_for(exp.source_kind),
                        source_content_sha256=exp.content_sha256,
                        decision='confirmed', note=(
                            'بازبینی دستی نوع تجربه پس از مطالعهٔ منبع. ' + rationale))
                else:
                    ExperienceReviewEvent.objects.create(
                        experience=exp, reviewer=request.user,
                        review_field=key, decision=SOURCE_DECISIONS[key],
                        evidence_url=rights_doc if key == 'copyright' else exp.source_url,
                        rationale=(
                            'بازبینی گروهی با تأیید مستقل بازبین. ' + rationale +
                            (' | مجوز استفاده از تحلیل مشتق‌شده از منبع بررسی شد.'
                             if key == 'copyright' else '')
                        ))
                created += 1
        if not created:
            # Already-reviewed ordinary decisions are an idempotent no-op.
            # Do not force the reviewer through the same approval again;
            # direct them to the still-missing rights evidence.
            messages.info(
                request,
                'بررسی‌های عادی انتخاب‌شده قبلاً ثبت شده‌اند و نیاز به تکرار ندارند. '
                'اگر هنوز امتیازی قابل انتشار نیست، مانعِ باقی‌مانده را '
                'در بخش مجوز استفاده از منبع ببینید.')
            return redirect(
                'admin:companies_company_checkpoint_release',
                object_id=company.pk)
    messages.success(
        request, f'{created} رویداد بررسی برای {len(selected_rows)} تجربه ثبت شد. '
        'هیچ نمره یا متنی خودکار منتشر نشده است.')
    return redirect('admin:companies_company_checkpoint_release', object_id=company.pk)
