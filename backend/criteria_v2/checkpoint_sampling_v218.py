"""Deterministic, privacy-preserving sampling plan for *independent* semantic QA.

Does not assess semantics, expose source text, call a model, or change approval.
All records are synthetic IDs/axis keys only; the reviewer must assess source
without viewing the proposed score first. The selected items are never gold.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .checkpoint_contract_v218 import load_handoff


def sample_semantic_review(rows, ledger, *, each=5, seed='jobiew-v218-independent-qa'):
    if type(each) is not int or not 1 <= each <= 50:
        raise ValueError('each must be an integer from 1 to 50')
    if not isinstance(seed, str) or not 1 <= len(seed) <= 100:
        raise ValueError('seed must be a short nonempty string')
    strata = {}
    for row in rows:
        exp_id = row['experience_id']
        if ledger[exp_id].get('exact_duplicate_of_experience_id') is not None:
            continue
        for axis, dim in row['prediction']['dimensions'].items():
            stratum = (row['kind'], axis, 'numeric' if dim['score'] is not None else 'null')
            strata.setdefault(stratum, []).append((exp_id, row['company_id']))
    selected = []
    counts = Counter()
    for (kind, axis, mode), cases in sorted(strata.items()):
        def sort_key(case):
            material = f'{seed}|{kind}|{axis}|{mode}|{case[0]}'.encode('utf-8')
            return hashlib.sha256(material).hexdigest()
        used_companies = set()
        ordered = sorted(cases, key=sort_key)
        # Give separate companies priority when possible to reduce correlated cases.
        diverse = []
        leftover = []
        for exp_id, cid in ordered:
            if cid in used_companies:
                leftover.append((exp_id, cid))
            else:
                used_companies.add(cid)
                diverse.append((exp_id, cid))
        for exp_id, _ in (diverse + leftover)[:each]:
            selected.append({'experience_id': exp_id, 'kind': kind,
                             'axis': axis, 'blind_score': None,
                             'blind_evidence_supported': None,
                             'blind_null_appropriate': None,
                             'reviewer_note': '', 'reviewed_by': ''})
            counts[f'{kind}/{axis}/{mode}'] += 1
    # Do not reveal proposed scores or strata in the reviewer task file.
    selected.sort(key=lambda item: (item['experience_id'], item['axis']))
    return selected, dict(sorted(counts.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Independent QA sample without source text or AI')
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--per-stratum', default=5, type=int)
    parser.add_argument('--seed', default='jobiew-v218-independent-qa')
    args = parser.parse_args(argv)
    rows, ledger, report = load_handoff(args.source, args.checkpoint)
    tasks, summary = sample_semantic_review(rows, ledger,
                each=args.per_stratum, seed=args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / 'blind_semantic_review_tasks.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in tasks),
        encoding='utf-8')
    (args.out_dir / 'private_sampling_manifest.json').write_text(json.dumps({
        'method': 'deterministic_per_axis_numeric_null_stratified',
        'independent_accuracy_established': False,
        'source_zip_sha256': report['source_zip_sha256'],
        'checkpoint_zip_sha256': report['checkpoint_zip_sha256'],
        'selected_axis_reviews': len(tasks),
        'by_stratum': summary,
        'caveat': 'Nonrepresentative oversample for review; not a confidence bound.'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'selected_axis_reviews': len(tasks), 'publication': 'DISABLED',
                      'independent_accuracy_established': False}))


if __name__ == '__main__':
    main()
