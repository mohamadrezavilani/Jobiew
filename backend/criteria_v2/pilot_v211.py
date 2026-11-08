"""Private offline dual-six human-reference pilot preparation and assembly.

No Django, API, DB access, internet calls, or publication. Story files and
human labels remain local and NEVER belong in version control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .quality_v210 import BENCHMARK_VERSION, BenchmarkError, evaluate
from .registry import axes_for

PILOT_VERSION = 'jobiew_dual6_pilot_v211'
PENDING = 'HUMAN_LABEL_REQUIRED'


class PilotError(ValueError):
    pass


def _length_bucket(story):
    n = len(story)
    return 'short' if n < 350 else 'medium' if n < 1100 else 'long'


def select_cases(candidates, *, per_kind=20, seed='20261108'):
    """Select bounded, reproducible and work/interview-balanced blind cases.

    Each candidate: {'local_id':positive int,'kind':work/interview,'story':str}.
    Strata are just source lengths; semantic representativeness is not claimed.
    """
    if type(per_kind) is not int or not 1 <= per_kind <= 50:
        raise PilotError('per_kind must be an integer in 1..50')
    if not isinstance(seed, str) or not 1 <= len(seed) <= 100:
        raise PilotError('seed must be a short nonempty string')
    if not isinstance(candidates, list) or len(candidates) > 100_000:
        raise PilotError('candidates must be a bounded JSON array')
    buckets = defaultdict(list)
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {'local_id', 'kind', 'story'}:
            raise PilotError('candidate must contain exactly local_id, kind, story')
        source_id, kind, story = (candidate[k] for k in ('local_id', 'kind', 'story'))
        if type(source_id) is not int or source_id <= 0 or kind not in ('work', 'interview'):
            raise PilotError('invalid candidate ID or kind')
        if source_id in seen:
            raise PilotError('duplicate source experience ID')
        seen.add(source_id)
        if not isinstance(story, str) or len(story.strip()) < 50 or len(story) > 8000:
            continue
        digest = hashlib.sha256(f'{seed}|{source_id}|{kind}'.encode('utf-8')).hexdigest()
        buckets[(kind, _length_bucket(story))].append((digest, source_id, story))
    results = []
    for kind in ('work', 'interview'):
        ordered = {}
        for bucket in ('short', 'medium', 'long'):
            ordered[bucket] = sorted(buckets[(kind, bucket)])
        counters = {b: 0 for b in ordered}
        # Round-robin across lengths prevents long reports dominating the pilot.
        for _ in range(per_kind):
            available = [b for b in ('short', 'medium', 'long') if counters[b] < len(ordered[b])]
            if not available:
                break
            bucket = min(available, key=lambda b: (counters[b], ('short', 'medium', 'long').index(b)))
            _, source_id, story = ordered[bucket][counters[bucket]]
            counters[bucket] += 1
            results.append({'case_id': f'{kind}-{len([x for x in results if x["kind"] == kind])+1:03d}',
                            'kind': kind, 'story': story, 'source_experience_id': source_id,
                            'length_group': bucket})
    return results


def make_private_documents(selected):
    stories = {'pilot_version': PILOT_VERSION, 'cases': []}
    gold = {'pilot_version': PILOT_VERSION, 'cases': []}
    predictions = {'pilot_version': PILOT_VERSION, 'cases': []}
    mapping = {'pilot_version': PILOT_VERSION, 'cases': []}
    for case in selected:
        case_id, kind, story = case['case_id'], case['kind'], case['story']
        stories['cases'].append({'case_id': case_id, 'kind': kind, 'story': story})
        gold['cases'].append({'case_id': case_id, 'kind': kind,
                              'gold': {axis.key: {'score': PENDING, 'evidence': ''}
                                       for axis in axes_for(kind)}})
        predictions['cases'].append({'case_id': case_id, 'prediction': None})
        mapping['cases'].append({'case_id': case_id, 'source_experience_id': case['source_experience_id'],
                                 'length_group': case['length_group']})
    return stories, gold, predictions, mapping


def combine_private_documents(stories, gold, predictions):
    """Validate aligned private files; require actual human labels and predictions.

    Reference labels are kept separate so annotators never see predictions.
    """
    for value in (stories, gold, predictions):
        if not isinstance(value, dict) or value.get('pilot_version') != PILOT_VERSION:
            raise PilotError('invalid pilot version')
        if not isinstance(value.get('cases'), list):
            raise PilotError('pilot cases must be an array')
    def index(value, allowed):
        result = {}
        for row in value['cases']:
            if not isinstance(row, dict) or set(row) != allowed:
                raise PilotError('pilot case schema mismatch')
            key = row.get('case_id')
            if not isinstance(key, str) or not key or key in result:
                raise PilotError('duplicate or invalid pilot case ID')
            result[key] = row
        return result
    gold_index = index(gold, {'case_id', 'kind', 'gold'})
    pred_index = index(predictions, {'case_id', 'prediction'})
    stories_index = index(stories, {'case_id', 'kind', 'story'})
    if not stories_index or set(stories_index) != set(gold_index) or set(stories_index) != set(pred_index):
        raise PilotError('stories, gold and prediction case IDs must match exactly')
    cases = []
    for case_id, source in stories_index.items():
        reviewed = gold_index[case_id]
        if source['kind'] != reviewed['kind']:
            raise PilotError('human label has incorrect source kind')
        if not isinstance(reviewed['gold'], dict):
            raise PilotError('human gold missing')
        for axis in axes_for(source['kind']):
            entry = reviewed['gold'].get(axis.key)
            if not isinstance(entry, dict) or entry.get('score') == PENDING:
                raise PilotError('human reference is incomplete; label every axis or null')
        if pred_index[case_id]['prediction'] is None:
            raise PilotError('prediction is missing for one or more pilot cases')
        cases.append({**source, 'gold': reviewed['gold'],
                      'prediction': pred_index[case_id]['prediction']})
    corpus = {'benchmark_version': BENCHMARK_VERSION, 'cases': cases}
    try:
        evaluate(corpus)
    except (BenchmarkError, ValueError) as exc:
        raise PilotError(str(exc)) from None
    return corpus


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local private pilot; no paid requests')
    subs = parser.add_subparsers(dest='command', required=True)
    build = subs.add_parser('prepare')
    build.add_argument('--candidates', required=True)
    build.add_argument('--output-dir', required=True)
    build.add_argument('--per-kind', type=int, default=20)
    build.add_argument('--seed', default='20261108')
    assemble = subs.add_parser('assemble')
    assemble.add_argument('--stories', required=True)
    assemble.add_argument('--gold', required=True)
    assemble.add_argument('--predictions', required=True)
    assemble.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            selected = select_cases(_load(args.candidates), per_kind=args.per_kind, seed=args.seed)
            if not selected:
                raise PilotError('no eligible stories to sample')
            output = Path(args.output_dir)
            output.mkdir(parents=True, exist_ok=False)
            data = make_private_documents(selected)
            for name, doc in zip(('stories.json', 'gold_template.json', 'predictions_template.json', 'mapping_private.json'), data):
                (output / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n',encoding='utf8')
            print('PILOT_PREPARE: PASS')
            print('PILOT_CASE_COUNTS: ' + json.dumps({kind: sum(x['kind']==kind for x in selected)
                           for kind in ('work', 'interview')}))
            print('PRIVATE_FILES: DO_NOT_COMMIT_OR_SHARE')
        else:
            corpus = combine_private_documents(_load(args.stories), _load(args.gold), _load(args.predictions))
            report = evaluate(corpus)
            report_path = Path(args.report)
            if report_path.exists():
                raise PilotError('will not overwrite existing quality report')
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            print('PILOT_QUALITY_REPORT: PASS')
            print(json.dumps({'cases':report['cases'],'metrics':report['metrics'],
                              'release_approved':False},ensure_ascii=False))
    except (PilotError, OSError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(2, f'PILOT_ERROR: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
