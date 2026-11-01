"""Overlay active PROVISIONAL revisions on original AI scores for staff-only use.

No history is deleted, no canonical assessment is recreated, and public or
human-verified aggregates are never changed by this module.
"""

def apply_active_semantic_overrides(rows):
    """Copy read-model rows and overlay the last matching activated revision.

    Every row needs dimension_id, content_hash and score (baseline). No override
    can apply if the source was re-crawled or its baseline changed. Duplicate AI
    runs remain ambiguous in the existing v11 aggregator.
    """
    from .models import SemanticScoreOverride
    source = list(rows)
    ids = [r['dimension_id'] for r in source if r.get('dimension_id') is not None]
    if not ids:
        return [dict(row) for row in source]
    # One bounded query per company, or one query per full export.
    selected = {}
    qs = SemanticScoreOverride.objects.filter(
        dimension_id__in=set(ids), status='active_provisional'
    ).order_by('-pk').values('dimension_id', 'baseline_score', 'source_content_sha256',
                              'action', 'proposed_score')
    for item in qs:
        selected.setdefault(item['dimension_id'], []).append(item)
    output = []
    for row in source:
        result = dict(row)
        for candidate in selected.get(row.get('dimension_id'), ()):
            if (candidate['baseline_score'] == row.get('score') and
                    candidate['source_content_sha256'].lower() == str(row.get('content_hash') or '').lower()):
                result['score'] = candidate['proposed_score'] if candidate['action'] == 'revise' else None
                result['semantic_override_active'] = True
                break
        output.append(result)
    return output
