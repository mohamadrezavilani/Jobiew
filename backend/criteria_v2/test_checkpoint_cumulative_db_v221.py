"""Source-bound private staging tests on synthetic Django records only.

Uses the shared v218 stage_one implementation. Does not enable publication,
connect to private user databases, or make external calls.
"""
from hashlib import sha256
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.test import TestCase

from companies.models import Company
from experiences.models import PublicExperience
from .checkpoint_cumulative_v221 import validate_cumulative, CheckpointError
from .engine_v207 import story_from_experience
from .management.commands.stage_dual6_checkpoint_v218 import check_candidate, stage_one
from .models import CriteriaAnalysis, CriteriaAxisScore
from .test_checkpoint_cumulative_v221 import synthetic, archive, SOURCE_SHA


class CumulativeCheckpointDBTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            id='synthetic-company', source_name='synthetic',
            source_url='https://example.invalid/cumulative-v221', display_name='شرکت تست خصوصی',
        )
        cls.other = Company.objects.create(
            id='synthetic-other', source_name='synthetic',
            source_url='https://example.invalid/cumulative-v221-other', display_name='شرکت دوم تست',
        )
        story = 'یک روایت ساختگی صرفاً برای تست اعتبارسنجی فرمت و نقل قول.'
        cls.exp = PublicExperience.objects.create(
            pk=1, company=cls.company, source_url='https://example.invalid/cumulative-v221/e1',
            source_kind='work', body=story, title='عنوان محرمانهٔ ساختگی',
            content_sha256='a'*64,
        )
        cls.story = story

    def _read_rows(self):
        payload = synthetic()
        # Synthetic archive's first source story digest must match Django's
        # independently reconstructed, redacted source text.
        from json import loads, dumps
        ledger = [loads(x) for x in payload['ledger.jsonl'].splitlines()]
        prediction = loads(payload['assistant_predictions.jsonl'])
        digest = sha256(story_from_experience(self.exp).encode('utf8')).hexdigest()
        ledger[0]['story_sha256'] = digest
        prediction['story_sha256'] = digest
        payload['ledger.jsonl'] = b'\n'.join(dumps(x, ensure_ascii=False).encode() for x in ledger)
        payload['assistant_predictions.jsonl'] = dumps(prediction, ensure_ascii=False).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.zip'
            checksum = archive(path, payload)
            rows, ledger, qa = validate_cumulative(
                path, expected_checkpoint_sha256=checksum,
                expected_source_sha256=SOURCE_SHA)
            return rows, ledger, qa

    def test_stage_one_is_private_six_axis_and_idempotent(self):
        rows, ledger, qa = self._read_rows()
        self.assertEqual(qa['reviewed'], 1)
        self.assertEqual(check_candidate(rows[0])[3], 'new')
        self.assertTrue(stage_one(rows[0]))
        self.assertFalse(stage_one(rows[0]))
        run = CriteriaAnalysis.objects.get(experience=self.exp)
        self.assertEqual(run.review_status, 'pilot_unverified')
        self.assertEqual(run.raw_payload['publication'], 'DISABLED')
        self.assertEqual(run.axis_scores.count(), 6)
        self.assertEqual(run.axis_scores.exclude(score__isnull=True).count(), 1)
        self.assertEqual(run.axis_scores.filter(semantic_status='unreviewed').count(), 6)

    def test_source_change_fails_without_creating_analysis(self):
        rows, ledger, qa = self._read_rows()
        PublicExperience.objects.filter(pk=1).update(body='این متن تغییر داده شده و منبع دیگر منطبق نیست')
        with self.assertRaises(CheckpointError):
            check_candidate(rows[0])
        self.assertEqual(CriteriaAnalysis.objects.count(), 0)

    def test_existing_legacy_run_is_preserved(self):
        rows, ledger, qa = self._read_rows()
        older = CriteriaAnalysis.objects.create(
            experience=self.exp, criteria_version='work6_v2',
            source_content_sha256='a'*64,
            model_name='legacy-private', prompt_version='v212',
            run_id='synthetic-v212-keep', review_status='pilot_unverified',
            raw_payload={'engine':'legacy-v212'},
        )
        self.assertTrue(stage_one(rows[0]))
        older.refresh_from_db()
        self.assertEqual(older.raw_payload['engine'], 'legacy-v212')
        self.assertEqual(CriteriaAnalysis.objects.count(), 2)
        self.assertEqual(CriteriaAxisScore.objects.filter(analysis=older).count(), 0)

    def test_duplicate_same_engine_conflict_blocks_without_overwrite(self):
        rows, ledger, qa = self._read_rows()
        run = CriteriaAnalysis.objects.create(
            experience=self.exp, criteria_version='work6_v2',
            source_content_sha256='a'*64,
            model_name='conflict', prompt_version='wrong',
            run_id='synthetic-colliding-engine', review_status='pilot_unverified',
            raw_payload={'engine':'jobiew_gpt6_private_checkpoint_v218'},
        )
        with self.assertRaises(CheckpointError):
            stage_one(rows[0])
        self.assertEqual(CriteriaAnalysis.objects.count(), 1)
        self.assertTrue(CriteriaAnalysis.objects.filter(pk=run.pk).exists())