"""PRD feasibility phase: staff-only, database READ-ONLY local evidence snapshot.

This does not evaluate any experience with AI, verify companies, or publish data.
Select *provisional* technology-company candidates; editorial confirmation is required.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from companies.models import Company
from experiences.models import PublicExperience

# Previously proposed examples, *not* independent verification of tech sector.
# These names only help avoid selecting random non-tech businesses from the corpus.
PREVIOUS_PROVISIONAL_NAMES = (
    'توسن', 'اسنپ فود', 'اسنپ‌فود', 'اسنپ', 'تپسی', 'صبانت',
    'ماورانت', 'کارناوال', 'داتکس', 'فالنیک', 'همکاران سیستم', 'تخفیفان',
)
FIELDS = (
    'company_id', 'company_name', 'company_source_url', 'source_work_records',
    'source_interview_records', 'coverage_band', 'identity_status', 'tech_status',
    'tehran_status', 'technology_company_confirmed', 'company_identity_confirmed',
    'reviewer_evidence_url', 'reviewer_notes', 'pilot_status',
)
REVIEW_FIELDS = (
    'company_id', 'company_name', 'experience_id', 'source_url', 'source_site',
    'published_jalali', 'crawled_at_utc', 'company_attribution_status',
    'independence_status', 'copyright_review', 'duplicate_exact_group',
    'duplicate_group_size', 'text_characters', 'quality_flags', 'reviewer_notes',
)


def normalized_text(value):
    s = unicodedata.normalize('NFKC', str(value or '')).replace('ي', 'ی').replace('ك', 'ک')
    s = s.replace('\u200c', ' ')
    return ' '.join(s.split()).casefold()


def narrative(exp):
    # Keep original content in export. This is ONLY for duplicate flagging.
    parts = [exp.body or '']
    for items in (exp.pros, exp.cons):
        if isinstance(items, list):
            parts.extend(str(item) for item in items if isinstance(item, (str, int, float)))
    return '\n'.join(p for p in parts if p.strip())


def significant_duplicate_key(value):
    text = normalized_text(value)
    # Tiny templated replies are not evidence of duplication.
    return hashlib.sha256(text.encode('utf-8')).hexdigest() if len(text) >= 40 else None


def to_iso(d):
    return d.isoformat() if d else None


def csv_write(path, columns, records):
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def plausible_candidate(company):
    if company.tech_status == 'rejected' or company.identity_status == 'rejected':
        return False
    if company.tech_status == 'verified':
        return True
    name = normalized_text(company.display_name)
    return any(normalized_text(seed) in name for seed in PREVIOUS_PROVISIONAL_NAMES)


def select_companies(all_companies, count, explicit_ids):
    by_id = {c.pk: c for c in all_companies}
    if explicit_ids:
        unique = list(dict.fromkeys(explicit_ids))
        if len(unique) != count:
            raise CommandError(f'--company-ids must contain exactly {count} unique IDs')
        invalid = [x for x in unique if x not in by_id]
        if invalid:
            raise CommandError('Unrecognized company IDs: ' + ', '.join(invalid[:5]))
        if any(by_id[x].work_count == 0 for x in unique):
            raise CommandError('All selected companies must have at least one work experience')
        return [by_id[x] for x in unique]

    pool = [c for c in all_companies if c.work_count > 0 and plausible_candidate(c)]
    # Explicit tech verification preferred within each coverage band; deterministic choices.
    pool.sort(key=lambda c: (-c.work_count, c.display_name, c.pk))
    if len(pool) <= count:
        return pool
    bands = [pool[i * len(pool) // 3:(i + 1) * len(pool) // 3] for i in range(3)]
    quota = [count // 3 + (1 if i < count % 3 else 0) for i in range(3)]
    chosen = []
    for band, needed in zip(bands, quota):
        ranked = sorted(band, key=lambda c: (c.tech_status != 'verified',
            -c.work_count, c.display_name, c.pk))
        chosen.extend(ranked[:needed])
    chosen_ids = {c.pk for c in chosen}
    if len(chosen) < count:
        for c in sorted(pool, key=lambda c: (c.tech_status != 'verified',-c.work_count,c.pk)):
            if c.pk not in chosen_ids:
                chosen.append(c)
                chosen_ids.add(c.pk)
                if len(chosen) == count:
                    break
    return sorted(chosen, key=lambda c: (-c.work_count, c.display_name, c.pk))


class Command(BaseCommand):
    help = 'Export a local read-only, PROVISIONAL 10-company feasibility sample, with provenance and quality flags; NO API calls.'

    def add_arguments(self, parser):
        parser.add_argument('--out', default='reports/feasibility_v50', help='New directory for PRIVATE local reports')
        parser.add_argument('--count', type=int, default=10)
        parser.add_argument('--company-ids', default='', help='Optional comma-separated exact IDs, exactly --count')

    def handle(self, *args, **options):
        count = options['count']
        if count < 1 or count > 50:
            raise CommandError('--count must be from 1 to 50')
        output = Path(options['out']).resolve()
        # Never modify an existing report directory, even partially.
        if output.exists():
            raise CommandError('Output already exists. Choose another --out path; nothing overwritten.')
        explicit = [x.strip() for x in options['company_ids'].split(',') if x.strip()]

        # Source_work_count is denormalized; calculate fresh counts using the actual rows.
        companies = list(Company.objects.annotate(
            work_count=Count('experiences', filter=Q(experiences__source_kind='work')),
            interview_count=Count('experiences', filter=Q(experiences__source_kind='interview')),
        ))
        selected = select_companies(companies, count, explicit)
        if not selected:
            raise CommandError('No candidate with work experiences found. Import/sync data first.')
        selected_ids = [c.pk for c in selected]
        selected_set = set(selected_ids)
        sorted_sizes = sorted((c.work_count for c in selected), reverse=True)
        # Band is relative within this trial sample, NOT a population quality claim.
        def band_for(c):
            rank = sorted_sizes.index(c.work_count)
            if rank < max(1, len(selected) // 3): return 'higher_relative'
            if rank < max(2, (2 * len(selected)) // 3): return 'middle_relative'
            return 'lower_relative'

        # Materialize only the sample experiences plus lightweight hashes across corpus.
        # Content is NOT sent over network and never written back to DB.
        samples = list(PublicExperience.objects.filter(
            company_id__in=selected_ids, source_kind='work'
        ).select_related('company').order_by('company_id', 'pk'))
        corpus_duplicate_counts = Counter()
        corpus_source_counts = Counter()
        corpus_company_sets = defaultdict(set)
        for item in PublicExperience.objects.filter(source_kind='work').only(
            'id', 'body', 'pros', 'cons', 'source_site', 'company_id'
        ).iterator(chunk_size=500):
            key = significant_duplicate_key(narrative(item))
            if key:
                corpus_duplicate_counts[key] += 1
                corpus_company_sets[key].add(item.company_id)
            corpus_source_counts[(item.source_site, 'work')] += 1
        for row in PublicExperience.objects.filter(source_kind='interview').values('source_site').annotate(n=Count('pk')):
            corpus_source_counts[(row['source_site'], 'interview')] += row['n']

        # First validate the complete planned output, then write files.
        candidate_rows = []
        for c in selected:
            candidate_rows.append(dict(
                company_id=c.pk, company_name=c.display_name,
                company_source_url=c.source_url,
                source_work_records=c.work_count,
                source_interview_records=c.interview_count,
                coverage_band=band_for(c), identity_status=c.identity_status,
                tech_status=c.tech_status, tehran_status=c.tehran_status,
                technology_company_confirmed='yes' if c.tech_status == 'verified' else 'REVIEW_REQUIRED',
                company_identity_confirmed='yes' if c.identity_status == 'verified' else 'REVIEW_REQUIRED',
                reviewer_evidence_url='', reviewer_notes='', pilot_status='PROVISIONAL_NOT_FINAL',
            ))
        review_rows = []
        json_records = []
        flag_counts = Counter()
        for item in samples:
            content = narrative(item)
            key = significant_duplicate_key(content)
            flags = []
            if not item.published_jalali.strip(): flags.append('missing_source_publication_date')
            if len(normalized_text(content)) < 40: flags.append('short_narrative')
            if key and corpus_duplicate_counts[key] > 1: flags.append('exact_text_duplicate_candidate')
            if key and len(corpus_company_sets[key]) > 1: flags.append('same_text_across_companies')
            if item.company_attribution_status != 'verified': flags.append('attribution_not_verified')
            if item.independence_status != 'verified': flags.append('independence_not_verified')
            if item.copyright_review != 'approved': flags.append('copyright_permission_not_approved')
            if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', content): flags.append('possible_email_pii')
            if re.search(r'(?<!\d)(?:\+98|0098|0)?9[0-9۰-۹]{9}(?!\d)', content): flags.append('possible_mobile_pii')
            flag_counts.update(flags)
            group_id = key[:16] if key and corpus_duplicate_counts[key] > 1 else ''
            review_rows.append(dict(
                company_id=item.company_id, company_name=item.company.display_name,
                experience_id=item.pk, source_url=item.source_url, source_site=item.source_site,
                published_jalali=item.published_jalali, crawled_at_utc=to_iso(item.crawled_at_utc) or '',
                company_attribution_status=item.company_attribution_status,
                independence_status=item.independence_status,
                copyright_review=item.copyright_review,
                duplicate_exact_group=group_id,
                duplicate_group_size=corpus_duplicate_counts[key] if key else 0,
                text_characters=len(content), quality_flags=';'.join(flags), reviewer_notes='',
            ))
            json_records.append(dict(
                company_id=item.company_id, company_name=item.company.display_name,
                source_site=item.source_site, source_url=item.source_url,
                experience_id=item.pk, source_kind='work',
                published_jalali=item.published_jalali or None,
                employment_period_jalali=item.employment_period_jalali or None,
                crawled_at_utc=to_iso(item.crawled_at_utc),
                title=item.title, job_title=item.job_title,
                original_body=item.body, original_pros=item.pros, original_cons=item.cons,
                original_content_sha256=item.content_sha256,
                duplicate_exact_group=group_id or None,
                quality_flags=flags,
                company_attribution_status=item.company_attribution_status,
                independence_status=item.independence_status,
                copyright_review=item.copyright_review,
                # These are deliberately not model-produced confidence/ratings.
                ai_scores_generated=False, ready_for_external_llm=False,
            ))
        all_coverage = [dict(company_id=c.pk, company_name=c.display_name,
            source_url=c.source_url, tech_status=c.tech_status,
            identity_status=c.identity_status, work_count=c.work_count,
            interviews_count=c.interview_count, selected_in_provisional_pilot='yes' if c.pk in selected_set else 'no')
            for c in companies if c.work_count or c.interview_count]
        all_coverage.sort(key=lambda c: (-c['work_count'], c['company_name']))
        source_rows = [dict(source_site=s, content_kind=k, records=n, legal_terms_checked='NO',
                            usable_for_external_ai='NOT_DETERMINED')
                       for (s, k), n in sorted(corpus_source_counts.items())]
        for site in ('linkedin.com', 'x.com'):
            if not any(r['source_site'] == site for r in source_rows):
                source_rows.append(dict(source_site=site, content_kind='work', records=0,
                    legal_terms_checked='NO', usable_for_external_ai='NOT_DETERMINED'))
        output.mkdir(parents=True, exist_ok=False)
        csv_write(output/'pilot_candidates.csv', FIELDS, candidate_rows)
        csv_write(output/'experience_review_queue.csv', REVIEW_FIELDS, review_rows)
        csv_write(output/'company_coverage.csv', (
            'company_id','company_name','source_url','tech_status','identity_status',
            'work_count','interviews_count','selected_in_provisional_pilot'), all_coverage)
        csv_write(output/'source_inventory.csv', (
            'source_site','content_kind','records','legal_terms_checked','usable_for_external_ai'), source_rows)
        with (output/'sample_work_experiences_PRIVATE.jsonl').open('w',encoding='utf-8') as f:
            for record in json_records:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
        warnings = []
        if len(selected) < count: warnings.append(f'Only {len(selected)} provisional candidates found; requested {count}.')
        if any(c.tech_status != 'verified' for c in selected):
            warnings.append('Technology-sector status NOT verified for every proposed company; human source-backed sign-off needed.')
        warnings.extend([
            'Company/source coverage does not prove legal permission to reuse or send text to an external model.',
            'Exact normalized text duplicates are candidates only; paraphrases/reposts and author independence need manual review.',
            'Work experiences only; interview content is excluded from model-input sample.',
            'Dates are preserved as source Jalali strings, without invented Gregorian conversions.',
            'Private sample contains ORIGINAL text and may include PII; never upload/share publicly before rights/privacy review.',
            'No AI inference or company-wide scores are generated.',
        ])
        summary = dict(version='v50_feasibility_stage_A', status='PROVISIONAL_NOT_SIGNED_OFF',
            generated_at_utc=datetime.now(timezone.utc).isoformat(), read_only_database=True,
            ai_network_requests=0, requested_companies=count, selected_companies=len(selected),
            work_records_exported=len(json_records), work_records_in_database=sum(n for (s,k),n in corpus_source_counts.items() if k == 'work'),
            companies_with_work_or_interviews=len(all_coverage),
            tech_verified_candidates=sum(c.tech_status == 'verified' for c in selected),
            flagged_records_by_type=dict(sorted(flag_counts.items())),
            warnings=warnings, deliverables=[
                'pilot_candidates.csv', 'company_coverage.csv', 'source_inventory.csv',
                'experience_review_queue.csv', 'sample_work_experiences_PRIVATE.jsonl', 'manifest.json'],
        )
        (output/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        self.stdout.write(json.dumps({'result':'OK_PROVISIONAL','output':str(output),
            'selected_companies':len(selected),'sample_work_experiences':len(json_records),
            'tech_verified_candidates':summary['tech_verified_candidates'],
            'read_only_database':True,'ai_network_requests':0},ensure_ascii=False))
