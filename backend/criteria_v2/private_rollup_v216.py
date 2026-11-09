"""Pure, read-only pilot roll-up. NEVER feed this result to public pages.

The input is ordered newest-first by source experience, and contains only
provisional AI pilot predictions. It is deliberately not a source of approved
company ratings. No IO, inference, model writes or rights status mutations.
"""
from .sufficiency_contract_v208 import make_sufficiency
from .registry import axes_for


def aggregate_pilot(kind, *, total_experiences, candidates):
    """Return provisional per-axis coverage from validated pilot cases only.

    candidates: sequence of (experience_id, integrity_ok, dimensions) with
      `dimensions` a mapping of all 6 keys to score (1..10 or None).
    A later/older duplicate run never silently overrides the newest row.
    Integrity failures contribute nothing, including abstentions.
    """
    expected = {x.key for x in axes_for(kind)}
    seen = set()
    rows = []
    valid_cases = 0
    invalid_cases = 0
    duplicate_cases = 0
    for exp_id, integrity_ok, dimensions in candidates:
        if type(exp_id) is not int or exp_id <= 0:
            raise ValueError('Invalid experience ID')
        if exp_id in seen:
            duplicate_cases += 1
            continue
        seen.add(exp_id)
        if not integrity_ok:
            invalid_cases += 1
            continue
        if not isinstance(dimensions, dict) or set(dimensions) != expected:
            invalid_cases += 1
            continue
        if any(score is not None and (type(score) is not int or not 1 <= score <= 10)
               for score in dimensions.values()):
            invalid_cases += 1
            continue
        valid_cases += 1
        rows.extend((exp_id, key, score) for key, score in dimensions.items())
    data = make_sufficiency(kind, total_experiences, rows)
    data.update({
        'pilot_valid_cases': valid_cases,
        'pilot_invalid_cases': invalid_cases,
        'pilot_duplicate_runs': duplicate_cases,
        'pilot_numeric_scores': sum(value is not None for _, _, value in rows),
        'pilot_abstentions': sum(value is None for _, _, value in rows),
        'review_status': 'pilot_unverified',
        'approved_for_publication': False,
    })
    return data
