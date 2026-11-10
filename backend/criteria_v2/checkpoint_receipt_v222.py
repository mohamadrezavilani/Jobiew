"""Verifiable receipts for *independently reviewed* GPT-6 checkpoint scores.

The receipt attests to a snapshot of the six stored axis records; it does not
establish a source's rights, attribution or real-world accuracy. Publication is
separately gated and refuses any post-review mutation.
"""
import hashlib
import json
from .checkpoint_contract_v218 import ENGINE, PROMPT
from .engine_v207 import story_from_experience, story_digest
from .registry import axes_for, version_for


def approved_checkpoint_digest(analysis):
    """Return current approved-run digest or None on any inconsistency.

    Source and six-axis evidence are revalidated on every publication query,
    so a stale or edited run cannot reuse a previous human approval receipt.
    """
    exp = analysis.experience
    raw = analysis.raw_payload
    if (analysis.review_status != 'approved' or
            analysis.criteria_version != version_for(exp.source_kind) or
            analysis.source_content_sha256 != exp.content_sha256 or
            analysis.prompt_version != PROMPT or not isinstance(raw, dict) or
            raw.get('engine') != ENGINE or
            raw.get('publication') != 'DISABLED' or
            raw.get('source_rights') != 'NOT_ESTABLISHED' or
            raw.get('semantic_accuracy') != 'NOT_ESTABLISHED'):
        return None
    story = story_from_experience(exp)
    digest = story_digest(story)
    if raw.get('story_sha256') != digest:
        return None
    axes = axes_for(exp.source_kind)
    scores = list(analysis.axis_scores.all())
    if len(scores) != 6 or {item.key for item in scores} != {axis.key for axis in axes}:
        return None
    lookup = {item.key: item for item in scores}
    rows = []
    numeric = 0
    for axis in axes:
        item = lookup[axis.key]
        if not isinstance(item.explanation, str) or not 8 <= len(item.explanation.strip()) <= 600:
            return None
        if item.score is None:
            if (item.confidence != 0 or item.evidence not in ([], None) or
                    item.semantic_status != 'abstained'):
                return None
        else:
            if (type(item.score) is not int or not 1 <= item.score <= 10 or
                    type(item.confidence) is not int or not 70 <= item.confidence <= 100 or
                    item.semantic_status != 'approved' or
                    not isinstance(item.evidence, list) or not item.evidence or
                    not all(isinstance(q, str) and 12 <= len(q) <= 450 and q in story and
                            not any(x in q for x in ('[email]', '[phone]', '[number]'))
                            for q in item.evidence)):
                return None
            numeric += 1
        rows.append([axis.key, item.score, item.confidence, item.evidence,
                     item.explanation, item.semantic_status])
    if numeric == 0:
        return None  # All-null experiences are not public quantitative evidence.
    material = [ENGINE, analysis.run_id, analysis.pk, exp.pk, exp.company_id,
                exp.source_kind, analysis.criteria_version, exp.content_sha256, digest, rows]
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_release_ready(analysis):
    """Read-only publication predicate: human audit + immutable snapshot + rights.

    Independent company/source/classification gates are checked by the caller.
    """
    from .models import CheckpointApprovalReceipt
    try:
        receipt = CheckpointApprovalReceipt.objects.select_related('score_review_event').get(
            analysis_id=analysis.pk)
    except CheckpointApprovalReceipt.DoesNotExist:
        return False
    if (receipt.source_content_sha256 != analysis.experience.content_sha256 or
            receipt.score_review_event.analysis_id != analysis.pk or
            receipt.score_review_event.reviewer_id != receipt.reviewer_id or
            receipt.score_review_event.source_content_sha256 != analysis.experience.content_sha256):
        return False
    scores = list(analysis.axis_scores.all())
    expected = {r.key: ('approve' if r.score is not None else 'abstain') for r in scores}
    if receipt.score_review_event.decisions != expected or len(expected) != 6:
        return False
    current = approved_checkpoint_digest(analysis)
    return current is not None and receipt.scores_sha256 == current