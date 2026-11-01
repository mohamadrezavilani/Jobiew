"""Private diagnostic aggregates of UNREVIEWED imported AI scores.

These means are descriptive of textual AI suggestions, NOT company ratings,
NOT independently verified and never for public presentation. Pure functions.
"""
from collections import defaultdict
from statistics import mean, pstdev
from .five_criteria_contract import KEYS


def provisional_company_aggregate(company_id, rows):
    """Compute per-criterion provisional statistics for exactly one company.

    * No assumption that different experience IDs imply different authors.
    * Multiple runs on same experience+dimension are ambiguous: discard ALL.
    * Repeated content hash within a criterion: keep first experience only.
    * NULL means abstain; never interpret it as a numeric zero.
    * No confidence weighting, no eligibility/publication decisions.
    """
    if not str(company_id or '').strip():
        raise ValueError('Explicit company_id is required')
    groups = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or str(row.get('company_id')) != str(company_id):
            raise ValueError('Missing or mixed company rows')
        key = row.get('dimension')
        exp = row.get('experience_id')
        if key not in KEYS or not str(exp or '').strip():
            raise ValueError('Unknown criterion or empty experience_id')
        score = row.get('score')
        if score is not None and (type(score) is not int or not 1 <= score <= 10):
            raise ValueError('Invalid AI score')
        groups[(key, str(exp))].append(row)

    result = {}
    for key in KEYS:
        seen_hashes = set()
        values = []
        abstained = 0
        ambiguous = 0
        content_duplicates = 0
        # Input ordering cannot change the mean or which duplicate content is kept.
        for (dim, exp), observations in sorted(groups.items()):
            if dim != key:
                continue
            if len(observations) != 1:
                ambiguous += len(observations)
                continue
            row = observations[0]
            content_hash = str(row.get('content_hash') or '').strip()
            if content_hash:
                if content_hash in seen_hashes:
                    content_duplicates += 1
                    continue
                seen_hashes.add(content_hash)
            if row['score'] is None:
                abstained += 1
            else:
                values.append(row['score'])
        result[key] = {
            'mean_provisional': round(mean(values), 2) if values else None,
            'stdev_provisional': round(pstdev(values), 2) if values else None,
            'n_provisional_used': len(values),
            'n_provisional_abstentions': abstained,
            'n_ambiguous_run_rows': ambiguous,
            'n_content_duplicates_excluded': content_duplicates,
            'min_provisional': min(values) if values else None,
            'max_provisional': max(values) if values else None,
            'status': 'UNREVIEWED_AI_RESEARCH_ONLY' if values else 'NO_SCORABLE_AI_EVIDENCE',
        }
    return {'company_id': str(company_id),
            'criteria_version': 'five_v1',
            'publication_status': 'NOT_APPROVED_FOR_PUBLICATION',
            'criteria': result}
