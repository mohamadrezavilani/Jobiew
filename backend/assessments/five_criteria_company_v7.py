"""Private company-scoped five-criterion research read model.

This module is deliberately read-only. No imported AI score is a public rating;
confidence is not a reliability probability. All results require explicit checks.
"""
from __future__ import annotations

from .five_criteria_aggregation import research_aggregate
from .five_criteria_contract import KEYS
from .five_criteria_provisional_v11 import provisional_company_aggregate
from .five_criteria_semantic_v17 import apply_active_semantic_overrides

MIN_INDEPENDENT = 3
LABELS = {
    'work_conditions_pressure': 'تعادل کار و زندگی و تناسب حجم کار',
    'management_environment': 'کیفیت مدیریت و محیط کاری',
    'growth_development': 'رشد و توسعه فردی و حرفه‌ای',
    'compensation_appreciation': 'جبران خدمات و فرهنگ قدردانی',
    'stability_security': 'ثبات و امنیت شغلی',
}


def research_aggregate_for_company(company_id, rows, *, min_independent=MIN_INDEPENDENT):
    """Fail closed on mixed-company input, unlike the historical single-company helper.

    Every row MUST carry a company_id; do not silently discard mismatches.
    This function makes no publication decision and returns research-only output.
    """
    if company_id is None or not str(company_id).strip():
        raise ValueError('Explicit nonempty company_id is required')
    checked = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get('company_id', '')) != str(company_id):
            raise ValueError('Mixed or missing company_id: refusing cross-company aggregation')
        checked.append(row)
    result = research_aggregate(checked, min_independent=min_independent)
    return {'company_id': str(company_id), **result}


def _review_verdict(dimension):
    """Latest event wins. Prefetch expected; do not assume older approvals persist."""
    events = dimension.human_review_events.all()
    latest = max(events, key=lambda e: (e.created_at, e.pk), default=None)
    return latest.verdict if latest else None


def build_company_research_preview(company, *, min_independent=MIN_INDEPENDENT):
    """Count imported observations and prepare a *staff-only* private visualization.

    No public endpoint can access this function directly. No source text/URL,
    user identity, reviewer identity, or raw quote is included in the output.
    """
    from django.db.models import Prefetch
    from .models import AiAssessment, AiDimension, AiHumanReviewEvent, FIVE_CRITERIA_VERSION

    qs = AiAssessment.objects.filter(
        experience__company_id=company.pk,
        experience__source_kind='work',
        criteria_version=FIVE_CRITERIA_VERSION,
    ).select_related('experience').prefetch_related(
        Prefetch('dimensions', queryset=AiDimension.objects.filter(key__in=KEYS).prefetch_related(
            Prefetch('human_review_events', queryset=AiHumanReviewEvent.objects.order_by('-created_at', '-pk'))
        ))
    ).order_by('pk')

    proposed = {k: 0 for k in KEYS}
    abstained = {k: 0 for k in KEYS}
    provisional_confidence = {k: [] for k in KEYS}
    exp_ids = set()
    gated_rows = []
    provisional_rows = []

    for assessment in qs:
        exp = assessment.experience
        if str(exp.company_id) != str(company.pk):
            raise ValueError('Cross-company join mismatch')
        exp_ids.add(exp.pk)
        rights = exp.copyright_review == 'approved'
        attribution = exp.company_attribution_status == 'verified'
        independence = exp.independence_status == 'verified'
        for dim in assessment.dimensions.all():
            if dim.score is None:
                abstained[dim.key] += 1
            else:
                proposed[dim.key] += 1
                provisional_confidence[dim.key].append(dim.confidence)
            provisional_rows.append({
                'dimension_id': dim.pk,
                'company_id': str(company.pk),
                'experience_id': str(exp.pk),
                'content_hash': exp.content_sha256,
                'dimension': dim.key,
                'score': dim.score,
            })
            gated_rows.append({
                'company_id': str(company.pk),
                'experience_id': str(exp.pk),
                'dimension': dim.key,
                'score': dim.score,
                'human_verified': _review_verdict(dim) == 'supported',
                'rights_verified': rights,
                'attribution_verified': attribution,
                'independence_verified': independence,
            })

    aggregate = research_aggregate_for_company(company.pk, gated_rows, min_independent=min_independent)
    provisional = provisional_company_aggregate(company.pk, apply_active_semantic_overrides(provisional_rows))
    company_identity_ok = company.identity_status == 'verified'
    criteria = []
    for k in KEYS:
        stats = aggregate['criteria'][k]
        draft = provisional['criteria'][k]
        mean = stats['mean_diagnostic'] if company_identity_ok else None
        count = stats['n_verified_independent']
        status = (
            'COMPANY_IDENTITY_UNVERIFIED' if not company_identity_ok else
            'INTERNAL_RESEARCH_ONLY' if mean is not None else
            'INSUFFICIENT_VERIFIED_DATA'
        )
        criteria.append({
            'key': k, 'label': LABELS[k], 'score': mean,
            'n_verified_independent': count,
            'n_provisional_scores': proposed[k],
            'n_abstentions': abstained[k],
            # Diagnostic means are ALWAYS private/unverified, regardless of company identity.
            # No estimate is implicitly accepted as an official company rating.
            **draft,
            'mean_ai_text_support_unvalidated': (
                round(sum(provisional_confidence[k]) / len(provisional_confidence[k]), 1)
                if provisional_confidence[k] else None
            ),
            'status': status,
        })

    return {
        'company_id': str(company.pk),
        'criteria_version': FIVE_CRITERIA_VERSION,
        'company_identity_verified': company_identity_ok,
        'unique_experiences_in_scope': len(exp_ids),
        'assessment_runs_in_scope': len(qs),
        'min_independent': min_independent,
        'criteria': criteria,
        'provisional_profile_available': any(c['mean_provisional'] is not None for c in criteria),
        'publication_status': 'NOT_APPROVED_FOR_PUBLICATION',
        'cacheable': False,
    }
