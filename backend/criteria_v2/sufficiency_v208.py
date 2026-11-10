"""Read-only, publication-gated Jobiew MVP sufficiency on reviewed dual-six data.

No API calls, writes, migrations or changes to historical five-axis scores.
The env switch is OFF by default; no unreviewed proposal can leak publicly.
"""
import os
from .engine_v207 import story_digest, story_from_experience
from .models import CriteriaAnalysis, CriteriaReviewEvent
from .registry import VERSIONS, axes_for
from .sufficiency_contract_v208 import MIN_SUFFICIENT_EXPERIENCES, make_sufficiency
from experiences.models import PublicExperience, ExperienceReviewEvent
from .checkpoint_contract_v218 import ENGINE as CHECKPOINT_ENGINE
from .checkpoint_receipt_v222 import checkpoint_release_ready, approved_checkpoint_digest
from .company_release_v224 import effective_release_proofs


def publication_enabled():
    return os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') == '1'


def configured_threshold():
    raw = os.environ.get('JOBIEW_MIN_SUFFICIENT_EXPERIENCES', str(MIN_SUFFICIENT_EXPERIENCES))
    try:
        threshold = int(raw)
    except (TypeError, ValueError):
        raise ValueError('Invalid JOBIEW_MIN_SUFFICIENT_EXPERIENCES') from None
    if not 2 <= threshold <= 1000:
        raise ValueError('JOBIEW_MIN_SUFFICIENT_EXPERIENCES must be between 2 and 1000')
    return threshold


def _latest_classifications(company, kind):
    """Latest review, including exclusion and stale hash, wins per experience."""
    reviews = (CriteriaReviewEvent.objects.filter(
        experience__company=company, source_kind=kind,
        criteria_version=VERSIONS[kind]
    ).order_by('experience_id', '-created_at', '-pk')
        .values('experience_id', 'decision', 'source_content_sha256'))
    latest = {}
    for row in reviews.iterator(chunk_size=1000):
        latest.setdefault(row['experience_id'],
                          (row['decision'], row['source_content_sha256']))
    return latest


def _checkpoint_rights_provenance_valid(exp):
    """Current rights, attribution and independence need append-only evidence."""
    for field, decision in (('copyright', 'approved'), ('attribution', 'verified'),
                            ('independence', 'verified')):
        latest = (ExperienceReviewEvent.objects.filter(experience=exp, review_field=field)
                  .order_by('-created_at', '-pk').first())
        if latest is None or latest.decision != decision or not latest.evidence_url:
            return False
    return True


def _approved_dimension_rows(company, kind):
    """Only latest approved, current-source, explicitly source-cleared analyses.

    Identity/time of authors are unknown in MVP. Do not invent verification.
    Known duplicate experiences are excluded; no fake independence threshold.
    """
    if company.identity_status != 'verified' or company.tech_status != 'verified':
        return []  # Additional publication safety, not a sufficiency threshold.
    latest_reviews = _latest_classifications(company, kind)
    released_proofs = effective_release_proofs(company)
    analyses = (CriteriaAnalysis.objects.filter(
        experience__company=company, experience__source_kind=kind,
        criteria_version=VERSIONS[kind], review_status='approved',
        experience__copyright_review='approved',
        experience__company_attribution_status='verified',
    ).exclude(experience__independence_status='duplicate')
     .select_related('experience')
     .prefetch_related('axis_scores')
     .order_by('experience_id', '-created_at', '-pk'))
    seen = set()
    rows = []
    valid_keys = {a.key for a in axes_for(kind)}
    for analysis in analyses.iterator(chunk_size=200):
        exp = analysis.experience
        if exp.pk in seen:
            continue
        seen.add(exp.pk)  # NEVER count more than one run for this experience.
        if latest_reviews.get(exp.pk) != ('confirmed', exp.content_sha256):
            continue
        if analysis.source_content_sha256 != exp.content_sha256:
            continue
        engine = analysis.raw_payload.get('engine')
        if os.environ.get('JOBIEW_COMPANY_RELEASE_ONLY_ENABLED', '0') == '1' and engine != CHECKPOINT_ENGINE:
            continue
        if engine == CHECKPOINT_ENGINE:
            if (released_proofs.get(str(analysis.pk)) != approved_checkpoint_digest(analysis) or
                    os.environ.get('JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED', '0') != '1'
                    or exp.independence_status != 'verified'
                    or not _checkpoint_rights_provenance_valid(exp)
                    or not checkpoint_release_ready(analysis)):
                continue
        elif engine != 'jobiew_dual6_evidence_v207':
            continue
        story = story_from_experience(exp)
        if analysis.raw_payload.get('story_sha256') != story_digest(story):
            continue
        for item in analysis.axis_scores.all():
            if item.key not in valid_keys or item.semantic_status != 'approved':
                continue
            if type(item.score) is not int or not 1 <= item.score <= 10:
                continue
            if type(item.confidence) is not int or item.confidence < 70:
                continue
            quotes = item.evidence
            if (not isinstance(quotes, list) or not quotes or
                not all(isinstance(q, str) and len(q) >= 12 and q in story
                        for q in quotes)):
                continue
            rows.append((exp.pk, item.key, item.score))
    return rows


def company_public_sufficiency(company):
    """Company-scoped, independent work and interview metrics.

    Call ONLY behind publication_enabled() and after explicit human approval
    of analyses and each score. Does not infer publication permission.
    """
    threshold = configured_threshold()
    output = {}
    for kind in ('work', 'interview'):
        total = PublicExperience.objects.filter(company=company, source_kind=kind).count()
        rows = _approved_dimension_rows(company, kind)
        scope = make_sufficiency(kind, total, rows, threshold=threshold)
        # Count distinct experiences with an actually published numeric axis;
        # the count is NOT equivalent to all approved or imported records.
        scope['used_experience_count'] = len({experience_id
                                               for experience_id, _, _ in rows})
        output[kind] = scope
    return output
