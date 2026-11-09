"""Jobiew data sufficiency contract v1.0 (MVP, executable pure logic).

Counts are distinct evaluable experiences *per dimension*, not sentences,
mentions, model runs, or total company experiences. Work/interview are separate.
Score aggregation (equal-weight arithmetic mean) is provisional; the supplied
MVP sufficiency policy does NOT prescribe a score aggregation formula.
"""
from decimal import Decimal, ROUND_HALF_UP
from .registry import axes_for

MIN_SUFFICIENT_EXPERIENCES = 6
STATUS_FA = {
    'insufficient': 'اطلاعات ناکافی',
    'partial': 'اطلاعات ناقص',
    'sufficient': 'اطلاعات کافی',
}
# Six fixed chart directions, clockwise, matching public framework SVG.
_SPOKES = ((0, -92), (80, -46), (80, 46), (0, 92), (-80, 46), (-80, -46))


def _valid_threshold(value):
    if type(value) is not int or not 2 <= value <= 1000:
        raise ValueError('Sufficiency threshold must be an integer between 2 and 1000')
    return value


def _valid_score(value):
    return type(value) is int and 1 <= value <= 10


def make_sufficiency(kind, total_experiences, dimension_rows, *, threshold=MIN_SUFFICIENT_EXPERIENCES):
    """Calculate deterministic six-axis data sufficiency.

    dimension_rows: (experience_id, axis_key, score) from *already validated*
    source-bound, independently approved scores. Null rows are abstentions.
    One experience may contribute to multiple dimensions, but never more
    than once to a given dimension. Conflicting repeats fail closed.

    No Django, DB access, source inference, publication, or AI requests.
    """
    axes = axes_for(kind)
    threshold = _valid_threshold(threshold)
    if type(total_experiences) is not int or total_experiences < 0:
        raise ValueError('total_experiences must be a nonnegative integer')
    keys = {a.key for a in axes}
    observed = {key: {} for key in keys}
    for experience_id, axis_key, score in dimension_rows:
        if axis_key not in keys:
            raise ValueError('Axis does not belong to the experience type')
        if type(experience_id) is not int or experience_id <= 0:
            raise ValueError('Invalid experience ID')
        if score is None:
            continue
        if not _valid_score(score):
            raise ValueError('Score must be an integer 1..10 or null')
        existing = observed[axis_key].get(experience_id)
        if existing is not None and existing != score:
            raise ValueError('Conflicting score for the same experience and axis')
        observed[axis_key][experience_id] = score

    result = []
    for i, axis in enumerate(axes):
        values = list(observed[axis.key].values())
        count = len(values)
        if count == 0:
            status, score, x, y = 'insufficient', None, None, None
        else:
            status = 'sufficient' if count >= threshold else 'partial'
            # Explicit provisional aggregation: one equal vote per experience.
            mean = Decimal(sum(values)) / Decimal(count)
            score = float(mean.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
            dx, dy = _SPOKES[i]
            x = round(130 + dx * score / 10, 2)
            y = round(112 + dy * score / 10, 2)
        result.append({
            'key': axis.key, 'label': axis.label, 'description': axis.description,
            'dimension_experience_count': count, 'score': score,
            'data_sufficiency_status': status, 'status_label': STATUS_FA[status],
            'chart_x': x, 'chart_y': y,
        })

    full_coverage = all(a['score'] is not None for a in result)
    return {
        'source_kind': kind,
        'total_experiences': total_experiences,
        'min_sufficient_experiences': threshold,
        'axes': result,
        'has_scores': any(a['score'] is not None for a in result),
        'full_coverage': full_coverage,
        'all_sufficient': all(a['data_sufficiency_status'] == 'sufficient' for a in result),
        # Partial-coverage shapes MUST NOT fill missing vertices as zeroes.
        'polygon_points': ' '.join(f"{a['chart_x']},{a['chart_y']}" for a in result) if full_coverage else '',
    }
