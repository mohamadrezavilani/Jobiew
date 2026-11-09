"""Pure safety contract; no DB/network. Run with Django unittest or standalone."""
import unittest
import hashlib
from copy import deepcopy
from types import SimpleNamespace

from .checkpoint_contract_v218 import (
    CheckpointError, select_batch, stage_run_id, verify_source_pair,
    verify_expected_archives,
)


class CheckpointV218PureTests(unittest.TestCase):
    def row(self, experience_id=1):
        return {'experience_id': experience_id, 'kind': 'work',
                'company_id': 'company-id',
                'source_content_sha256': 'a' * 64,
                'story_sha256': 'b' * 64,
                'review_status': 'unverified_private_proposal',
                'prediction': {'detected_kind': 'work', 'kind_confidence': 85,
                               'dimensions': {'test': {'score': None}}}}

    def test_run_id_is_stable(self):
        row = self.row()
        self.assertEqual(stage_run_id(row), stage_run_id(deepcopy(row)))

    def test_changed_company_and_kind_change_run_id(self):
        a = self.row()
        b = deepcopy(a)
        b['company_id'] = 'other-company'
        self.assertNotEqual(stage_run_id(a), stage_run_id(b))
        b = deepcopy(a)
        b['kind'] = 'interview'
        self.assertNotEqual(stage_run_id(a), stage_run_id(b))

    def test_different_prediction_requires_different_run(self):
        a = self.row()
        b = deepcopy(a)
        b['prediction']['kind_confidence'] = 75
        self.assertNotEqual(stage_run_id(a), stage_run_id(b))

    def test_limit_and_cursor(self):
        rows = [self.row(i) for i in range(1, 5)]
        ledger = {i: {'exact_duplicate_of_experience_id': None} for i in range(1, 5)}
        selected, duplicate_count = select_batch(rows, ledger, after_id=1, limit=2)
        self.assertEqual([x['experience_id'] for x in selected], [2, 3])
        self.assertEqual(duplicate_count, 0)

    def test_duplicates_are_skipped(self):
        rows = [self.row(i) for i in range(1, 5)]
        ledger = {i: {'exact_duplicate_of_experience_id': None} for i in range(1, 5)}
        ledger[2]['exact_duplicate_of_experience_id'] = 1
        selected, skipped = select_batch(rows, ledger, limit=3)
        self.assertEqual([x['experience_id'] for x in selected], [1, 3, 4])
        self.assertEqual(skipped, 1)

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            select_batch([], {}, limit=501)

    def test_bad_cursor_rejected(self):
        with self.assertRaises(ValueError):
            select_batch([], {}, after_id=-1)

    def test_apply_requires_exact_external_sha_pins(self):
        qa = {'source_zip_sha256': 'a' * 64, 'checkpoint_zip_sha256': 'b' * 64}
        self.assertTrue(verify_expected_archives(qa, 'a' * 64, 'b' * 64))
        with self.assertRaises(CheckpointError):
            verify_expected_archives(qa, '', 'b' * 64)
        with self.assertRaises(CheckpointError):
            verify_expected_archives(qa, 'a' * 64, 'c' * 64)

    def test_source_mismatch_refused(self):
        exp = SimpleNamespace(pk=1, company_id='different', source_kind='work',
                              content_sha256='a'*64, copyright_review='pending',
                              company_attribution_status='unverified', independence_status='unknown')
        with self.assertRaises(CheckpointError):
            verify_source_pair(self.row(), exp, 'sample story')

    def test_blocked_source_refused(self):
        exp = SimpleNamespace(pk=1, company_id='company-id', source_kind='work',
                              content_sha256='a'*64, copyright_review='blocked',
                              company_attribution_status='unverified', independence_status='unknown')
        row = self.row()
        row['story_sha256'] = hashlib.sha256(b'sample story').hexdigest()
        with self.assertRaisesRegex(CheckpointError, 'SOURCE_EXPLICITLY_BLOCKED'):
            verify_source_pair(row, exp, 'sample story')

    def test_unapproved_prediction_refused(self):
        exp = SimpleNamespace(pk=1, company_id='company-id', source_kind='work',
                              content_sha256='a'*64, copyright_review='pending',
                              company_attribution_status='unverified', independence_status='unknown')
        row = self.row()
        row['story_sha256'] = hashlib.sha256(b'sample story').hexdigest()
        row['review_status'] = 'approved'
        with self.assertRaisesRegex(CheckpointError, 'PROPOSAL_NOT_UNVERIFIED'):
            verify_source_pair(row, exp, 'sample story')

if __name__ == '__main__':
    unittest.main()
