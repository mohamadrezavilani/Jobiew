"""Offline, non-publishing human-reference benchmark for Jobiew's dual-six AI.

Never calls external APIs, reads databases or logs source text in reports.
All quality metrics are descriptive; no model becomes publication-approved here.
The input corpus and story text must stay outside the tracked repository.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .registry import axes_for

BENCHMARK_VERSION = 'jobiew_dual6_quality_v210'


class BenchmarkError(ValueError):
    pass


def _check_score(value, field):
    if value is not None and (type(value) is not int or not 1 <= value <= 10):
        raise BenchmarkError(f'{field}: score must be an integer 1..10 or null')


def _nonempty_quote(quote, story, label):
    if not isinstance(quote, str) or not 12 <= len(quote) <= 450 or quote not in story:
        raise BenchmarkError(f'{label}: quoted evidence must be an exact source substring (12..450 chars)')


def _gold_dimensions(kind, story, value):
    keys = {axis.key for axis in axes_for(kind)}
    if not isinstance(value, dict) or set(value) != keys:
        raise BenchmarkError('Gold reference must cover exactly six axes of the correct kind')
    result = {}
    for key, item in value.items():
        if not isinstance(item, dict) or set(item) != {'score', 'evidence'}:
            raise BenchmarkError('Gold item must have exactly score and evidence')
        score, evidence = item['score'], item['evidence']
        _check_score(score, 'gold.' + key)
        if score is None:
            if evidence != '':
                raise BenchmarkError('Gold abstention must have empty evidence')
        else:
            _nonempty_quote(evidence, story, 'gold.' + key)
        result[key] = score
    return result


def _prediction(kind, story, value):
    if not isinstance(value, dict) or set(value) != {'detected_kind', 'kind_confidence', 'dimensions'}:
        raise BenchmarkError('Prediction must have detected_kind, kind_confidence, dimensions')
    detected = value['detected_kind']
    if detected not in ('work', 'interview', 'unclear'):
        raise BenchmarkError('Invalid predicted kind')
    confidence = value['kind_confidence']
    if type(confidence) is not int or not 0 <= confidence <= 100:
        raise BenchmarkError('Invalid kind confidence')
    keys = {axis.key for axis in axes_for(kind)}
    dims = value['dimensions']
    if not isinstance(dims, dict) or set(dims) != keys:
        raise BenchmarkError('Prediction axes must match the recorded experience kind')
    result = {}
    unsupported = []
    for key, item in dims.items():
        if not isinstance(item, dict) or set(item) != {'score', 'confidence', 'evidence', 'explanation'}:
            raise BenchmarkError('Prediction item must include score, confidence, evidence, explanation')
        score, conf = item['score'], item['confidence']
        _check_score(score, 'prediction.' + key)
        if type(conf) is not int or not 0 <= conf <= 100:
            raise BenchmarkError('Invalid dimension confidence')
        evidence, explanation = item['evidence'], item['explanation']
        if not isinstance(explanation, str) or not explanation.strip():
            raise BenchmarkError('Missing prediction explanation')
        if not isinstance(evidence, str):
            raise BenchmarkError('Prediction evidence must be a string')
        if score is None:
            if conf != 0 or evidence:
                unsupported.append(key)
        else:
            if conf < 70 or not 12 <= len(evidence) <= 450 or evidence not in story or any(
                marker in evidence for marker in ('[email]', '[phone]', '[number]')
            ):
                unsupported.append(key)
        result[key] = score
    return detected, result, unsupported


def evaluate(corpus):
    """Evaluate a local, explicitly human-labelled corpus. No raw text in result."""
    if not isinstance(corpus, dict) or corpus.get('benchmark_version') != BENCHMARK_VERSION:
        raise BenchmarkError('Unsupported benchmark version')
    cases = corpus.get('cases')
    if not isinstance(cases, list) or not cases:
        raise BenchmarkError('At least one labelled case is required')
    seen = set()
    counts = {'work': 0, 'interview': 0}
    totals = defaultdict(lambda: {'reference_scored': 0, 'prediction_scored': 0,
                                   'true_scored': 0, 'both_scored': 0,
                                   'absolute_error_sum': 0, 'within_one': 0})
    mismatched_kind = 0
    unsupported_quotes = 0
    unsupported_cases = 0
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'case_id', 'kind', 'story', 'gold', 'prediction'}:
            raise BenchmarkError('Every case needs case_id, kind, story, gold, prediction')
        case_id, kind, story = case['case_id'], case['kind'], case['story']
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 120 or case_id in seen:
            raise BenchmarkError('Case IDs must be unique nonempty strings')
        seen.add(case_id)
        if kind not in counts or not isinstance(story, str) or len(story.strip()) < 30:
            raise BenchmarkError('Invalid kind or source story too short')
        counts[kind] += 1
        gold = _gold_dimensions(kind, story, case['gold'])
        detected, predicted, unsupported = _prediction(kind, story, case['prediction'])
        mismatched_kind += detected != kind
        unsupported_quotes += len(unsupported)
        unsupported_cases += bool(unsupported)
        for key in gold:
            tally = totals[key]
            g, p = gold[key], predicted[key]
            tally['reference_scored'] += g is not None
            tally['prediction_scored'] += p is not None
            tally['true_scored'] += (g is not None and p is not None)
            if g is not None and p is not None:
                tally['both_scored'] += 1
                tally['absolute_error_sum'] += abs(g - p)
                tally['within_one'] += abs(g - p) <= 1
    per_axis = {}
    micro = defaultdict(int)
    for key, t in sorted(totals.items()):
        for metric, value in t.items():
            micro[metric] += value
        both = t['both_scored']
        per_axis[key] = {'reference_scored': t['reference_scored'],
                         'prediction_scored': t['prediction_scored'],
                         'both_scored': both,
                         'mean_absolute_error': round(t['absolute_error_sum'] / both, 3) if both else None,
                         'within_one_ratio': round(t['within_one'] / both, 3) if both else None}
    both = micro['both_scored']
    ref_count, pred_count = micro['reference_scored'], micro['prediction_scored']
    correct_scored = both
    precision = correct_scored / pred_count if pred_count else None
    recall = correct_scored / ref_count if ref_count else None
    return {
        'benchmark_version': BENCHMARK_VERSION,
        'cases': len(cases), 'cases_by_kind': counts,
        'kind_disagreement_cases': mismatched_kind,
        'invalid_evidence_or_confidence_axes': unsupported_quotes,
        'cases_with_invalid_evidence_or_confidence': unsupported_cases,
        'metrics': {
            'score_mae_when_both_scored': round(micro['absolute_error_sum'] / both, 3) if both else None,
            'score_within_one_when_both_scored': round(micro['within_one'] / both, 3) if both else None,
            'scoring_decision_precision': round(precision, 3) if precision is not None else None,
            'scoring_decision_recall': round(recall, 3) if recall is not None else None,
            'reference_scored_axes': ref_count, 'predicted_scored_axes': pred_count,
        },
        'per_axis': per_axis,
        'release_approved': False,
        'review_note': 'Descriptive offline metrics only. Independent expert review, representative samples, licensing and publication approval remain required.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline human reference benchmark; no API/DB.')
    parser.add_argument('--input', required=True, help='Private local JSON (do not commit)')
    parser.add_argument('--output', help='Optional aggregate-only JSON report')
    args = parser.parse_args(argv)
    raw = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    try:
        report = evaluate(raw)
    except BenchmarkError as exc:
        parser.exit(2, f'BENCHMARK_INVALID: {exc}\n')
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
