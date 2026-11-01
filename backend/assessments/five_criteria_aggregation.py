"""Five-criterion *internal research* aggregation.

No real company ratings are emitted without validated evidence and independent
source checks. This module does not mutate RatingSnapshot or publish anything.
"""
from __future__ import annotations
from statistics import mean, pstdev
from .five_criteria_contract import KEYS

REQUIRED_GATES = ('human_verified', 'rights_verified', 'attribution_verified', 'independence_verified')


def research_aggregate(rows, *, min_independent=3):
    """rows: iterable of private, explicitly reviewed, per-experience dimension facts.

    Fields: experience_id, dimension, score (1..10), four REQUIRED_GATES flags.
    Any repeated experience+dimension is treated as ambiguous and removed; a
    validation process must identify the canonical assessment before aggregation.
    Separate author independence must be verified upstream, not inferred from IDs.
    Never use model-reported confidence as aggregation weight.
    """
    if type(min_independent) is not int or min_independent < 3:
        raise ValueError('The internal sample gate cannot be below 3 independent experiences')
    staged = {}
    duplicates = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get('dimension')
        exp = row.get('experience_id')
        score = row.get('score')
        if key not in KEYS or not exp or type(score) is not int or not 1 <= score <= 10:
            continue
        ident = (key, str(exp))
        if ident in staged:
            duplicates.add(ident)
            continue
        if not all(row.get(flag) is True for flag in REQUIRED_GATES):
            continue
        staged[ident] = score
    for ident in duplicates:
        staged.pop(ident, None)
    result = {}
    for key in KEYS:
        values = [score for (dim, _), score in staged.items() if dim == key]
        count = len(values)
        result[key] = {'n_verified_independent': count,
                       'mean_diagnostic': round(mean(values), 2) if count >= min_independent else None,
                       'stdev_diagnostic': round(pstdev(values), 2) if count >= min_independent else None,
                       'status': 'INTERNAL_RESEARCH_ONLY' if count >= min_independent else 'INSUFFICIENT_VERIFIED_DATA'}
    return {'criteria_version': 'five_v1', 'publication_status': 'NOT_APPROVED_FOR_PUBLICATION',
            'min_independent': min_independent, 'criteria': result}
