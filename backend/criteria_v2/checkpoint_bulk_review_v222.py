"""Private, evidence-checked company-wide adjudication of GPT-6 proposals.

Never changes source/rights/attribution/classification. Records one immutable
six-axis decision per analysis plus a tamper-evident receipt for scored runs.
A separate public publication switch and rights gates remain mandatory.
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
from experiences.models import PublicExperience
from .checkpoint_access_v218 import authorize_checkpoint
from .checkpoint_contract_v218 import ENGINE, PROMPT, STATUS
from .engine_v207 import story_digest, story_from_experience
from .models import (CriteriaAnalysis, CriteriaAxisScore, CriteriaScoreReviewEvent,
                     CheckpointApprovalReceipt)
from .pilot_dashboard_v213 import _private, _valid_analysis
from .checkpoint_receipt_v222 import approved_checkpoint_digest

MAX_COMPANY_RUNS = 1000


def _candidate_runs(company):
    return list(CriteriaAnalysis.objects.filter(
        experience__company=company, raw_payload__engine=ENGINE,
        review_status=STATUS,
    ).select_related('experience', 'experience__company')
     .prefetch_related('axis_scores').order_by('experience_id', 'pk')[:MAX_COMPANY_RUNS + 1])


def _status(run, previously_reviewed):
    exp = run.experience
    raw = run.raw_payload
    if (previously_reviewed or not isinstance(raw, dict) or
            run.prompt_version != PROMPT or
            raw.get('engine') != ENGINE or
            raw.get('source_rights') != 'NOT_ESTABLISHED' or
            raw.get('semantic_accuracy') != 'NOT_ESTABLISHED' or
            raw.get('publication') != 'DISABLED' or
            raw.get('story_sha256') != story_digest(story_from_experience(exp))):
        return 'درخواست بازبینی مجدد یا تغییر داده'
    if (exp.copyright_review == 'blocked' or
            exp.company_attribution_status == 'rejected' or
            exp.independence_status == 'duplicate'):
        return 'منبع مسدود، انتساب ردشده یا تکراری'
    if not _valid_analysis(run, story_from_experience(exp)):
        return 'شواهد یا شش معیار نامعتبر/قدیمی'
    return ''


def _prepare(company):
    runs = _candidate_runs(company)
    if len(runs) > MAX_COMPANY_RUNS:
        raise Http404('Company exceeds private bulk review safety cap; use an editorial batch plan')
    reviewed = set(CriteriaScoreReviewEvent.objects.filter(
        analysis_id__in=[r.pk for r in runs]).values_list('analysis_id', flat=True))
    ready = []
    rows = []
    digest_rows = []
    for run in runs:
        exp = run.experience
        axis_rows = sorted(run.axis_scores.all(), key=lambda x: x.key)
        reason = _status(run, run.pk in reviewed)
        numeric = sum(x.score is not None for x in axis_rows)
        if not reason:
            ready.append(run)
        rows.append({'run': run, 'numeric': numeric, 'reason': reason,
                     'rights_ready': exp.copyright_review == 'approved',
                     'attribution_ready': exp.company_attribution_status == 'verified',
                     'independence_ready': exp.independence_status == 'verified'})
        digest_rows.append([
            run.pk, run.run_id, run.review_status, run.prompt_version,
            run.raw_payload, exp.pk, exp.company_id, exp.source_kind, exp.content_sha256,
            story_digest(story_from_experience(exp)), exp.copyright_review,
            exp.company_attribution_status, exp.independence_status,
            run.pk in reviewed,
            [[a.key, a.score, a.confidence, a.evidence, a.explanation, a.semantic_status]
             for a in axis_rows],
        ])
    encoded = json.dumps(digest_rows, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return rows, ready, hashlib.sha256(encoded).hexdigest()


@never_cache
@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def company_bulk_review(request, pk):
    authorize_checkpoint(request)
    if request.method == 'POST' and not request.user.has_perm(
            'criteria_v2.add_criteriascorereviewevent'):
        raise PermissionDenied('Score adjudication permission required')
    company = get_object_or_404(Company, pk=pk)
    if request.method == 'GET':
        rows, ready, token = _prepare(company)
        return _private(request, 'criteria_v2/checkpoint_bulk_review_v222.html', {
            'company': company, 'rows': rows, 'ready_count': len(ready),
            'total_count': len(rows), 'token': token, 'cap': MAX_COMPANY_RUNS,
            'can_approve': request.user.has_perm('criteria_v2.add_criteriascorereviewevent'),
            'admin_mode': request.resolver_match.url_name == 'companies_company_checkpoint_bulk',
        })
    note = (request.POST.get('note') or '').strip()
    if (request.POST.get('confirm_reviewed') != 'yes' or
            request.POST.get('confirm_private') != 'yes' or
            not 20 <= len(note) <= 1200 or
            not request.POST.get('snapshot') or
            not request.POST.get('ready_count', '').isdigit()):
        return HttpResponse('EXPLICIT_HUMAN_REVIEW_ATTESTATION_REQUIRED', status=400)
    selected_raw = request.POST.getlist('selected')
    if (not selected_raw or len(selected_raw) > MAX_COMPANY_RUNS or
            any(not x.isascii() or not x.isdecimal() or not x.isdigit() for x in selected_raw) or
            len(selected_raw) != len(set(selected_raw))):
        return HttpResponse('INVALID_BULK_REVIEW_SELECTION', status=400)
    selected_ids = {int(x) for x in selected_raw}
    with transaction.atomic():
        # Serialize competing reviewers, and lock each source to prevent stale
        # company/source changes while human decisions are recorded.
        company = Company.objects.select_for_update().get(pk=pk)
        list(PublicExperience.objects.select_for_update().filter(company=company)
             .order_by('pk').values_list('pk', flat=True))
        rows, ready, current = _prepare(company)
        if (not ready or current != request.POST['snapshot'] or
                len(ready) != int(request.POST['ready_count'])):
            return HttpResponse('STALE_OR_INELIGIBLE_COMPANY_REVIEW', status=409)
        ready_ids = {run.pk for run in ready}
        if not selected_ids.issubset(ready_ids):
            return HttpResponse('INVALID_OR_INELIGIBLE_BULK_SELECTION', status=400)
        ready = [run for run in ready if run.pk in selected_ids]
        # The snapshot includes six complete quotes/scores, source identity
        # and previous-review state. Recheck once while source locks are held.
        approved_runs = 0
        for run in ready:
            decisions = {axis.key: ('approve' if axis.score is not None else 'abstain')
                         for axis in run.axis_scores.all()}
            numeric = sum(v == 'approve' for v in decisions.values())
            updates = []
            for axis in run.axis_scores.all():
                updates.append((axis.pk, 'approved' if axis.score is not None else 'abstained'))
            for axis_id, value in updates:
                CriteriaAxisScore.objects.filter(pk=axis_id, semantic_status='unreviewed').update(
                    semantic_status=value)
            CriteriaAnalysis.objects.filter(pk=run.pk, review_status=STATUS).update(
                review_status='approved' if numeric else 'no_evaluable_scores')
            review = CriteriaScoreReviewEvent.objects.create(
                analysis=run, reviewer=request.user,
                source_content_sha256=run.experience.content_sha256,
                decisions=decisions,
                note='بازبینی گروهی خصوصی با تأیید شواهد توسط بازبین. ' + note,
            )
            if numeric:
                # Reload affected axis statuses from DB before creating the
                # tamper-evident receipt used by the future public gate.
                validated = CriteriaAnalysis.objects.select_related('experience').get(pk=run.pk)
                fingerprint = approved_checkpoint_digest(validated)
                if fingerprint is None:
                    raise ValueError('POST_REVIEW_SIX_AXIS_INTEGRITY_FAILURE')
                CheckpointApprovalReceipt.objects.create(
                    analysis=validated, score_review_event=review, reviewer=request.user,
                    source_content_sha256=run.experience.content_sha256,
                    scores_sha256=fingerprint, batch_token=current,
                )
            approved_runs += 1
    messages.success(request, f'{approved_runs} پرونده بازبینی و در حسابرسی خصوصی ثبت شد؛ انتشار عمومی انجام نشد.')
    if request.resolver_match.url_name == 'companies_company_checkpoint_bulk':
        return redirect('admin:companies_company_checkpoint_bulk', object_id=pk)
    return redirect('dual-checkpoint-bulk-v222', pk=pk)