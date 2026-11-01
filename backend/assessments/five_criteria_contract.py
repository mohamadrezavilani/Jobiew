"""The five-criterion v1 contract. Strict, independent of database and any AI service.

DIRECTION (2026-10 v14 clarification): ALL FIVE scores are benefit-oriented.
For historical key work_conditions_pressure: a HIGH score means healthy
work-life balance and manageable workload; HIGH pressure means LOW score.
The key is retained to preserve historical imports and avoid blind inversion.
"""
from __future__ import annotations

KEYS = (
    'work_conditions_pressure', 'management_environment', 'growth_development',
    'compensation_appreciation', 'stability_security',
)


class InvalidFiveCriteria(ValueError):
    pass


def validate_annotations(row):
    """Return five canonical metric dicts; reject mixed/legacy or malformed records.

    Confidence is subjective *text-support*, never calibrated correctness.
    An abstention is NULL, not numeric zero. Evidence text is not independently verified.
    """
    if not isinstance(row, dict):
        raise InvalidFiveCriteria('Row is not an object')
    dims = row.get('dimensions')
    if not isinstance(dims, dict) or set(dims) != set(KEYS):
        raise InvalidFiveCriteria('Exactly the five active dimension keys are required')
    output = {}
    for key in KEYS:
        item = dims[key]
        if not isinstance(item, dict):
            raise InvalidFiveCriteria(f'{key}: not an object')
        score = item.get('score')
        if score is not None and (type(score) is not int or score < 1 or score > 10):
            raise InvalidFiveCriteria(f'{key}: invalid score')
        confidence = item.get('confidence_evidence_support_unvalidated', 0)
        if type(confidence) is not int or confidence < 0 or confidence > 100:
            raise InvalidFiveCriteria(f'{key}: invalid confidence')
        evidence = item.get('evidence', '')
        if not isinstance(evidence, str):
            raise InvalidFiveCriteria(f'{key}: evidence must be text')
        if score is None:
            if confidence != 0 or evidence.strip():
                raise InvalidFiveCriteria(f'{key}: abstention must have zero confidence and no evidence')
        elif not evidence.strip():
            raise InvalidFiveCriteria(f'{key}: scored dimension requires evidence')
        output[key] = {'score': score, 'confidence': confidence,
                       'evidence': [{'quote': evidence.strip(), 'field': 'unverified_ai_evidence'}] if score is not None else [],
                       'explanation': str(item.get('no_score_reason') or '') if score is None else '',
                       'status': str(item.get('status') or '')}
    return output
