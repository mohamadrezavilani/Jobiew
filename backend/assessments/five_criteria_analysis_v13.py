"""Read-only, research-only summaries for private company reports."""
from assessments.five_criteria_contract import KEYS
from assessments.five_criteria_company_v7 import LABELS


def analyze_provisional_criteria(criteria):
    """Only within-company extremes; no overall/official company score or rating.

    Incomplete values stay missing and cannot be interpreted as zero.
    """
    found=[]
    for item in criteria:
        value=item.get('mean_provisional')
        if value is not None:
            if type(value) not in (int,float) or not 1 <= value <= 10:
                raise ValueError('Provisional mean out of range')
            found.append({'key':item['key'],'label':LABELS[item['key']],
                         'mean':value,'n':item['n_provisional_used']})
    strengths=[];weaknesses=[]
    if len(found)>=2:
        high=max(c['mean'] for c in found)
        low=min(c['mean'] for c in found)
        if high>low:
            strengths=[c['label'] for c in found if c['mean']==high]
            weaknesses=[c['label'] for c in found if c['mean']==low]
    return {'available_count':len(found),'missing_count':len(KEYS)-len(found),
            'total_scored_observations':sum(c['n'] for c in found),
            'strengths':strengths,'weaknesses':weaknesses,
            'all_equal':len(found)>=2 and not strengths,
            'has_internal_comparison':bool(strengths)}
