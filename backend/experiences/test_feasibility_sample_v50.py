"""Phase-A acceptance tests: no writes to database, no LLM calls, no misleading approvals."""
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from companies.models import Company
from experiences.models import PublicExperience
from experiences.management.commands.feasibility_sample_v50 import (
    select_companies, normalized_text, significant_duplicate_key,
)


class FeasibilityPilotV50Tests(TestCase):
    def make_company(self, id, name, status='unverified'):
        return Company.objects.create(
            id=id, source_url=f'https://tajrobewiki.com/companies/{id}',
            source_name=name, display_name=name, tech_status=status,
        )

    def make_review(self, company, idx, text, kind='work', **kwargs):
        return PublicExperience.objects.create(
            company=company, source_url=f'https://tajrobewiki.com/reviews/{idx}',
            source_site='tajrobewiki.com', source_kind=kind,
            title=f'Title {idx}', body=text, pros=[], cons=[],
            content_sha256='x' * 64, **kwargs,
        )

    def read_csv(self, p):
        with p.open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))

    def test_export_preserves_exact_sources_and_flags_duplicate_across_companies(self):
        c1 = self.make_company('c1', 'توسن', 'verified')
        c2 = self.make_company('c2', 'تپسی')
        duplicate = 'شرکت در طول مدت طولانی از من خواست تمام روزها اضافه کار بدون حقوق انجام دهم.'
        a = self.make_review(c1, 1, duplicate, published_jalali='۱۴۰۵/۰۲/۱۲')
        b = self.make_review(c2, 2, duplicate)
        # Out-of-sample duplicate must still be seen in full-corpus duplicate detection.
        c3 = self.make_company('c3', 'شرکت نامرتبط')
        self.make_review(c3, 3, duplicate)
        self.make_review(c1, 4, 'مصاحبه درباره حقوق و مزایا انجام شد.', kind='interview')
        before = list(PublicExperience.objects.values_list('pk', 'source_url'))
        with TemporaryDirectory() as directory:
            out = Path(directory) / 'stage_a'
            call_command('feasibility_sample_v50', out=str(out), count=2,
                         company_ids='c1,c2', verbosity=0)
            exported = [json.loads(line) for line in
                (out / 'sample_work_experiences_PRIVATE.jsonl').read_text('utf-8').splitlines()]
            self.assertEqual(len(exported), 2)
            self.assertEqual({r['experience_id'] for r in exported}, {a.pk, b.pk})
            self.assertEqual(exported[0]['original_body'], duplicate)
            self.assertEqual(exported[0]['published_jalali'], '۱۴۰۵/۰۲/۱۲')
            self.assertEqual(exported[0]['source_kind'], 'work')
            self.assertFalse(exported[0]['ai_scores_generated'])
            self.assertFalse(exported[0]['ready_for_external_llm'])
            reviews = self.read_csv(out / 'experience_review_queue.csv')
            self.assertTrue(all('exact_text_duplicate_candidate' in r['quality_flags'] for r in reviews))
            self.assertTrue(all(r['duplicate_group_size'] == '3' for r in reviews))
            self.assertEqual(reviews[0]['duplicate_exact_group'],reviews[1]['duplicate_exact_group'])
            self.assertEqual(len(self.read_csv(out/'pilot_candidates.csv')), 2)
            self.assertEqual(json.loads((out/'manifest.json').read_text('utf-8'))['status'], 'PROVISIONAL_NOT_SIGNED_OFF')
            self.assertEqual(list(PublicExperience.objects.values_list('pk', 'source_url')), before)
            self.assertEqual(Company.objects.get(pk='c1').tech_status, 'verified')

    def test_no_silent_overwrite_existing_output(self):
        c = self.make_company('c1', 'توسن', 'verified')
        self.make_review(c, 1, 'یک متن که به اندازه کافی بلند باشد تا در خروجی ثبت شود.')
        with TemporaryDirectory() as directory:
            out = Path(directory) / 'out'
            out.mkdir()
            (out / 'sentinel.txt').write_text('DO NOT MODIFY')
            with self.assertRaisesRegex(CommandError, 'already exists'):
                call_command('feasibility_sample_v50', out=str(out), count=1, company_ids='c1')
            self.assertEqual((out/'sentinel.txt').read_text(), 'DO NOT MODIFY')

    def test_no_candidates_does_not_make_output_dir(self):
        with TemporaryDirectory() as directory:
            out = Path(directory) / 'out'
            with self.assertRaisesRegex(CommandError, 'No candidate'):
                call_command('feasibility_sample_v50', out=str(out), count=2)
            self.assertFalse(out.exists())

    def test_default_proposes_verified_and_curated_not_unrelated(self):
        unrelated = self.make_company('c1','کارخانه تولید کفش')
        known = self.make_company('c2','توسن','verified')
        provisional = self.make_company('c3','اسنپ')
        for idx, c in enumerate((unrelated,known,provisional),1):
            self.make_review(c,idx,'گزارش کار در محیط شرکت همراه با توضیحات و ارتباط با مدیریت داخلی.')
        with TemporaryDirectory() as directory:
            out = Path(directory) / 'out'
            call_command('feasibility_sample_v50',out=str(out),count=2)
            names={r['company_name'] for r in self.read_csv(out/'pilot_candidates.csv')}
            self.assertEqual(names, {'توسن','اسنپ'})
            self.assertEqual(len(self.read_csv(out/'company_coverage.csv')),3)

    def test_rejects_unknown_or_zero_work_or_wrong_count(self):
        c1=self.make_company('c1','توسن','verified')
        c2=self.make_company('c2','تپسی')
        self.make_review(c1,1,'داستان یک روز کاری متعارف در شرکت و محیط کار.')
        with TemporaryDirectory() as directory:
            out=Path(directory)/'out'
            for ids, count, reason in [('c1,c2',2,'at least one'),('c1,notfound',2,'Unrecognized'),('c1,c1',2,'exactly')]:
                with self.assertRaisesRegex(CommandError,reason):
                    call_command('feasibility_sample_v50',out=str(out),count=count,company_ids=ids)
            self.assertFalse(out.exists())

    def test_flag_private_information_without_sending_content(self):
        c=self.make_company('c1','توسن','verified')
        self.make_review(c,1,'ارتباط مستقیم از طریق mail@example.com با تیم مهندسی این شرکت برقرار شد.')
        with TemporaryDirectory() as directory:
            out=Path(directory)/'out'
            with patch('urllib.request.urlopen',side_effect=AssertionError('NETWORK USED')):
                call_command('feasibility_sample_v50',out=str(out),count=1,company_ids='c1')
            review=self.read_csv(out/'experience_review_queue.csv')[0]
            self.assertIn('possible_email_pii',review['quality_flags'])
            self.assertIn('copyright_permission_not_approved',review['quality_flags'])
            self.assertIn('attribution_not_verified',review['quality_flags'])

    def test_unicode_normalization_and_short_strings(self):
        self.assertEqual(normalized_text('كاري  ايران'),normalized_text('کاری ایران'))
        self.assertIsNone(significant_duplicate_key('خیلی خوب'))
        self.assertEqual(significant_duplicate_key('الف '*40),significant_duplicate_key('الف\u200c'*39+'الف'))
