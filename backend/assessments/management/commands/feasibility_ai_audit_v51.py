"""Offline read-only audit of historical AI extraction for the feasibility agreement.

This is diagnostic, not human validation and not permission to publish scores.
"""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from assessments.models import AiAssessment, LEGACY_DIMENSIONS, LEGACY_CRITERIA_VERSION

DIMENSION_KEYS = [name for name, _ in LEGACY_DIMENSIONS]


def compact(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split())


def evidence_fragments(evidence):
    """Only literal quote/text fields can be tested for exact presence in review."""
    if not isinstance(evidence, list):
        return []
    fragments = []
    for item in evidence:
        if isinstance(item, dict):
            for key in ('quote', 'text', 'snippet'):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    fragments.append(val)
                    break
        elif isinstance(item, str) and item.strip():
            fragments.append(item)
    return fragments


def shape_flags(dim, original):
    """Mechanical diagnostics only, never an automatic judgment of semantic correctness."""
    flags = []
    score = dim.score
    conf = dim.confidence
    evidence = dim.evidence
    if score is None:
        if conf != 0:
            flags.append('no_score_nonzero_confidence')
        if evidence:
            flags.append('no_score_has_evidence')
    else:
        if conf == 0:
            flags.append('score_zero_confidence')
        if not isinstance(evidence, list) or not evidence:
            flags.append('score_missing_evidence')
        fragments = evidence_fragments(evidence)
        if fragments:
            n_source = compact(original)
            if not any(compact(part) in n_source for part in fragments):
                flags.append('literal_evidence_not_found_in_review')
        elif evidence:
            flags.append('evidence_needs_manual_text_check')
    if dim.semantic_status != 'approved':
        flags.append('semantic_review_not_approved')
    return flags


def csv_write(path, headers, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


class Command(BaseCommand):
    help = 'Read-only offline AI extraction audit: no scoring, no publication, no external API calls.'

    def add_arguments(self, parser):
        parser.add_argument('--out', required=True, help='New directory only; will never overwrite reports.')
        parser.add_argument('--pilot-csv', help='Optional pilot_candidates.csv from feasibility_sample_v50')

    def handle(self, *args, **opts):
        out = Path(opts['out']).resolve()
        if out.exists():
            raise CommandError('Output already exists; choose a NEW folder to preserve evidence.')
        pilot_ids = []
        pilot_names = {}
        if opts.get('pilot_csv'):
            pilot_path = Path(opts['pilot_csv'])
            if not pilot_path.is_file():
                raise CommandError('Pilot CSV does not exist')
            with pilot_path.open('r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                if not {'company_id', 'company_name'}.issubset(reader.fieldnames or []):
                    raise CommandError('Pilot CSV requires company_id, company_name')
                for row in reader:
                    ident = (row.get('company_id') or '').strip()
                    if ident and ident not in pilot_names:
                        pilot_names[ident] = row['company_name']
                        pilot_ids.append(ident)
        # Query completely before creating directory: missing DB must not leave partial artifacts.
        assessments = list(AiAssessment.objects.filter(criteria_version=LEGACY_CRITERIA_VERSION).select_related('experience', 'experience__company')
                           .prefetch_related('dimensions').order_by('id'))
        out.mkdir(parents=True, exist_ok=False)
        private_path = out / 'historical_ai_source_PRIVATE.jsonl'
        csv_rows = []
        flags_count = Counter()
        dims_seen = Counter()
        covered = defaultdict(set)
        invalid_experience = 0
        with private_path.open('w', encoding='utf-8') as private:
            for assessment in assessments:
                experience = assessment.experience
                company = experience.company
                rows = list(assessment.dimensions.all())
                by_dim = {item.key: item for item in rows}
                original = '\n'.join([
                    experience.title, experience.body,
                    json.dumps(experience.pros, ensure_ascii=False),
                    json.dumps(experience.cons, ensure_ascii=False),
                ])
                if experience.source_kind != 'work':
                    invalid_experience += 1
                dimensions = {}
                for key in DIMENSION_KEYS:
                    dim = by_dim.get(key)
                    if dim is None:
                        flags = ['missing_dimension_record']
                        value = {'score': None, 'confidence': None, 'evidence': [], 'explanation': '',
                                 'semantic_status': 'missing'}
                    else:
                        flags = shape_flags(dim, original)
                        value = {'score': dim.score, 'confidence': dim.confidence,
                                 'evidence': dim.evidence, 'explanation': dim.explanation,
                                 'semantic_status': dim.semantic_status}
                        dims_seen[key] += 1
                        if dim.score is not None:
                            covered[(company.pk, key)].add(experience.pk)
                    flags_count.update(flags)
                    value['mechanical_flags'] = flags
                    dimensions[key] = value
                    csv_rows.append({
                        'assessment_id': assessment.pk, 'experience_id': experience.pk,
                        'company_id': company.pk, 'company_name': company.display_name,
                        'dimension': key, 'score': value['score'], 'confidence': value['confidence'],
                        'evidence_items': len(value['evidence']) if isinstance(value['evidence'], list) else 0,
                        'semantic_status': value['semantic_status'],
                        'mechanical_flags': '|'.join(flags),
                        'source_url': experience.source_url,
                        'human_company_correct': '', 'human_evidence_relevant': '',
                        'human_dimension_correct': '', 'human_score_supported': '',
                        'human_time_context_correct': '', 'human_independence_checked': '',
                        'human_notes': '',
                    })
                private.write(json.dumps({
                    'assessment_id': assessment.pk, 'experience_id': experience.pk,
                    'company_id': company.pk, 'company_name': company.display_name,
                    'company_verification': {'identity': company.identity_status,
                                             'tech': company.tech_status},
                    'source_kind': experience.source_kind,
                    'source_site': experience.source_site, 'source_url': experience.source_url,
                    'source_published_jalali': experience.published_jalali,
                    'source_content_sha256': experience.content_sha256,
                    'source_review_status': {'attribution': experience.company_attribution_status,
                                             'copyright': experience.copyright_review,
                                             'independence': experience.independence_status},
                    'title': experience.title, 'body': experience.body,
                    'pros': experience.pros, 'cons': experience.cons,
                    'model_name': assessment.model_name, 'prompt_version': assessment.prompt_version,
                    'run_id': assessment.run_id,
                    'published': assessment.publish_approved,
                    'independent_review_status': assessment.independent_review_status,
                    'dimensions': dimensions,
                }, ensure_ascii=False) + '\n')
        if hasattr(private_path, 'chmod'):
            try:
                private_path.chmod(0o600)
            except OSError:
                pass
        headers = ['assessment_id','experience_id','company_id','company_name','dimension','score',
                   'confidence','evidence_items','semantic_status','mechanical_flags','source_url',
                   'human_company_correct','human_evidence_relevant','human_dimension_correct',
                   'human_score_supported','human_time_context_correct','human_independence_checked','human_notes']
        csv_write(out / 'dimension_human_review_PRIVATE.csv', headers, csv_rows)
        coverage_rows = []
        for company_id in pilot_ids:
            for key in DIMENSION_KEYS:
                coverage_rows.append({'company_id': company_id, 'company_name': pilot_names[company_id],
                                      'dimension': key,
                                      'historical_assessed_experiences_with_score': len(covered[(company_id,key)]),
                                      'reliability_or_readiness': 'NOT_DETERMINED'})
        csv_write(out / 'pilot_ai_coverage.csv',
                  ['company_id','company_name','dimension','historical_assessed_experiences_with_score',
                   'reliability_or_readiness'], coverage_rows)
        manifest = {
            'version': 'v51_offline_historical_ai_audit',
            'status': 'STRUCTURAL_DIAGNOSTIC_ONLY_NO_HUMAN_SIGNOFF',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'database_writes': 0, 'external_api_requests': 0,
            'historical_assessments': len(assessments),
            'dimension_rows_in_review_worksheet': len(csv_rows),
            'dimensions_expected_per_assessment': len(DIMENSION_KEYS),
            'actual_dimensions_by_key': {k: dims_seen[k] for k in DIMENSION_KEYS},
            'flag_counts': dict(sorted(flags_count.items())),
            'non_work_source_assessments': invalid_experience,
            'pilot_companies_in_input': len(pilot_ids),
            'pilot_companies_with_historical_ai': len({a.experience.company_id for a in assessments
                                                     if a.experience.company_id in pilot_names}),
            'assessments_without_pilot_match': sum(a.experience.company_id not in pilot_names
                                                    for a in assessments) if pilot_names else None,
            'deliverables': ['manifest.json','pilot_ai_coverage.csv',
                             'dimension_human_review_PRIVATE.csv','historical_ai_source_PRIVATE.jsonl'],
            'limitations': [
                'No AI inference is performed and no scores are published or aggregated.',
                'A mechanical flag is NOT proof of incorrect semantics; absence of flags is NOT a pass.',
                'Evidence exact-match check may give false alarms on paraphrases, normalization or field choices.',
                'Historical AI rows are not evidence of sufficient coverage for ten companies.',
                'The two PRIVATE files include traceable review data or original user-created text; keep local.',
                'No human validation, copyright review, attribution signoff, or independent-author checks are performed.',
            ],
        }
        (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        self.stdout.write(json.dumps({'status': 'ok', 'out': str(out),
                                      'historical_assessments': len(assessments),
                                      'pilot_companies_with_historical_ai': manifest['pilot_companies_with_historical_ai'],
                                      'total_structural_flags': sum(flags_count.values()),
                                      'database_writes': 0, 'external_api_requests': 0}, ensure_ascii=False))
