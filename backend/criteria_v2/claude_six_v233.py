"""On-demand Claude second opinion over the CURRENT six work/interview axes.

No automatic calls, no five-axis fallback, no score mutation, and no publication.
The run is permanently bound to the source and six-axis analysis snapshot.
"""
import hashlib
import json
import os
from django.db import transaction
from django.utils import timezone

from .claude_six_models_v233 import ClaudeSixCheck
from .checkpoint_access_v218 import authorize_checkpoint
from .checkpoint_contract_v218 import ENGINE
from .checkpoint_private_v218 import _private_run_valid
from .engine_v207 import (build_request, call_claude, safe_usage,
                          story_from_experience, story_digest, validate_response)
from .models import CriteriaAnalysis
from .registry import axes_for

DEFAULT_LIMIT = 10
DEFAULT_MODEL = 'claude-sonnet-5-5'


def configured_limit():
    try:
        return min(100, max(0, int(os.environ.get(
            'JOBIEW_CLAUDE_SIX_LIMIT', str(DEFAULT_LIMIT)))))
    except ValueError:
        return 0


def enabled():
    return (os.environ.get('JOBIEW_CLAUDE_SIX_ENABLED', '0') == '1'
            and bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())
            and configured_limit() > 0)


def can_send_source(exp):
    """Explicit audited rights approval; URL of a post alone is not consent."""
    from experiences.models import ExperienceReviewEvent
    event = (ExperienceReviewEvent.objects.filter(
        experience=exp, review_field='copyright')
        .order_by('-created_at', '-pk').first())
    return (exp.copyright_review == 'approved' and event is not None
            and event.decision == 'approved'
            and isinstance(event.evidence_url, str)
            and event.evidence_url.startswith('https://'))


def snapshot(analysis):
    exp = analysis.experience
    story = story_from_experience(exp)
    axes = axes_for(exp.source_kind)
    by_key = {row.key: row for row in analysis.axis_scores.all()}
    if len(by_key) != 6 or set(by_key) != {axis.key for axis in axes}:
        raise ValueError('سند شش معیار این تجربه کامل نیست.')
    scores = {}
    for axis in axes:
        row = by_key[axis.key]
        scores[axis.key] = {
            'score': row.score, 'confidence': row.confidence,
            'evidence': row.evidence, 'explanation': row.explanation,
        }
    material = [analysis.pk, analysis.run_id, analysis.review_status,
                exp.pk, exp.content_sha256, exp.source_kind,
                analysis.criteria_version, scores]
    digest = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False).encode()).hexdigest()
    return story, scores, digest


def valid_analysis(analysis):
    exp = analysis.experience
    if (analysis.raw_payload.get('engine') != ENGINE
            or analysis.review_status not in (
                'pilot_unverified', 'approved', 'no_evaluable_scores')):
        return False
    return _private_run_valid(analysis, story_from_experience(exp))


def comparison_rows(analysis, check):
    """Only display a result when both the source and GPT-6 scores are unchanged."""
    if check is None or not valid_analysis(analysis):
        return [], False
    story, original, fingerprint = snapshot(analysis)
    if (check.source_sha256 != story_digest(story)
            or check.score_sha256 != fingerprint):
        return [], False
    results = check.claude_results if isinstance(check.claude_results, dict) else {}
    rows = []
    for axis in axes_for(analysis.experience.source_kind):
        other = results.get(axis.key) or {}
        one = original[axis.key]
        delta = (other.get('score') - one['score']
                 if type(other.get('score')) is int and type(one['score']) is int
                 else None)
        rows.append({
            'label': axis.label,
            'gpt': one['score'],
            'claude': other.get('score'),
            'delta': delta,
            'different': one['score'] != other.get('score'),
            'confidence': other.get('confidence'),
            'evidence': other.get('evidence') or [],
            'explanation': other.get('explanation') or '—',
        })
    return rows, True


def run_one(analysis, user):
    """Single paid HTTP request at most; results remain private and advisory."""
    if not enabled():
        raise ValueError('Claude ۶+۶ غیرفعال است یا کلید سرویس تنظیم نشده است.')
    if not valid_analysis(analysis):
        raise ValueError('شواهد GPT-6 معتبر یا به‌روز نیست؛ اجرای Claude ممکن نیست.')
    if not can_send_source(analysis.experience):
        raise ValueError('قبل از ارسال متن به Claude، مجوز مستند پردازش خارجی منبع باید بررسی شود.')
    story, original, digest = snapshot(analysis)
    model = os.environ.get('JOBIEW_CLAUDE_SIX_MODEL', DEFAULT_MODEL)
    # Validate request (including model ID and source length) before reserving a run.
    payload = build_request(analysis.experience.source_kind, story, model)
    with transaction.atomic():
        analysis = (CriteriaAnalysis.objects.select_for_update()
                    .select_related('experience').get(pk=analysis.pk))
        if not valid_analysis(analysis):
            raise ValueError('در فاصلهٔ بررسی، امتیازهای GPT-6 تغییر کرده‌اند.')
        current_story, current_original, current_digest = snapshot(analysis)
        if story != current_story or digest != current_digest:
            raise ValueError('دادهٔ منبع تغییر کرده است؛ صفحه را تازه کن.')
        prior = ClaudeSixCheck.objects.filter(analysis=analysis).first()
        if prior is not None:
            return prior, False
        if ClaudeSixCheck.objects.count() >= configured_limit():
            raise ValueError('سقف درخواست‌های Claude تمام شده است؛ بدون اجازهٔ جدید فراخوانی نمی‌شود.')
        check = ClaudeSixCheck.objects.create(
            analysis=analysis, requested_by=user, model_id=model,
            source_sha256=story_digest(story), score_sha256=digest,
            original_scores=original)
    try:
        response = call_claude(payload)
        validated = validate_response(
            response, kind=analysis.experience.source_kind, story=story)
        check.status = ('completed' if validated['status'] == 'unreviewed'
                        else 'needs_review')
        check.claude_results = validated['dimensions'] or {}
        if check.status == 'completed':
            comparison = {}
            for axis in axes_for(analysis.experience.source_kind):
                key = axis.key
                old, new = original[key]['score'], check.claude_results[key]['score']
                comparison[key] = {'original': old, 'claude': new,
                                   'changed': old != new}
            check.comparison = comparison
        usage = safe_usage(response)
        check.input_tokens = usage.get('input_tokens', 0)
        check.output_tokens = usage.get('output_tokens', 0)
    except Exception as exc:
        # Never write private vendor responses or source text into error logs/audit.
        check.status = 'failed'
        msg = str(exc)
        check.error_code = (msg[:70] if msg.startswith(
            ('ANTHROPIC_', 'MODEL_', 'SOURCE_')) else type(exc).__name__)
    check.finished_at = timezone.now()
    check.save(update_fields=[
        'status', 'claude_results', 'comparison', 'input_tokens',
        'output_tokens', 'error_code', 'finished_at'])
    return check, True
