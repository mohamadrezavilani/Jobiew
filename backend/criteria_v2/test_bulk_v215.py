"""Fully offline unit tests: no Django, no network, no database."""
import unittest
from .bulk_v215 import (
    deterministic_run_id, choose_batch, validate_budget,
    sanitized_failure_code, MAX_PAID_PER_INVOCATION,
)


class BulkV215PureTests(unittest.TestCase):
    def test_deterministic_run(self):
        x = deterministic_run_id(123, 'a'*64, 'claude-sonnet-4-6')
        self.assertEqual(x, deterministic_run_id(123, 'a'*64, 'claude-sonnet-4-6'))
        self.assertNotEqual(x, deterministic_run_id(124, 'a'*64, 'claude-sonnet-4-6'))
        self.assertNotEqual(x, deterministic_run_id(123, 'b'*64, 'claude-sonnet-4-6'))
        self.assertTrue(x.startswith('dual6v215_'))

    def test_bool_id_refused(self):
        with self.assertRaises(ValueError):
            deterministic_run_id(True, 'a'*64, 'claude-sonnet-4-6')

    def test_bad_digest_refused(self):
        with self.assertRaises(ValueError):
            deterministic_run_id(1, 'x'*64, 'claude-sonnet-4-6')

    def test_bad_model_refused(self):
        with self.assertRaises(ValueError):
            deterministic_run_id(1, 'a'*64, 'gpt-other-model')

    def test_limit_boundary(self):
        validate_budget(MAX_PAID_PER_INVOCATION, 0)
        with self.assertRaises(ValueError):validate_budget(11,0)
        with self.assertRaises(ValueError):validate_budget(0,0)

    def test_negative_cursor_refused(self):
        with self.assertRaises(ValueError):validate_budget(1,-1)

    def test_boolean_limit_refused(self):
        with self.assertRaises(ValueError):validate_budget(True,0)

    def test_batch_bounded(self):
        rows=[(1,'work','copyright_not_approved'),(2,'work','ready'),
              (3,'interview','ready'),(4,'work','ready')]
        result=choose_batch(rows,limit=2)
        self.assertEqual(result['selected_count'],2)
        self.assertEqual(result['last_scanned_id'],3)
        self.assertEqual(result['scanned'],3)
        self.assertEqual(result['blockers_in_scan']['copyright_not_approved'],1)

    def test_zero_ready(self):
        result=choose_batch([(1,'work','copyright_not_approved')],limit=3)
        self.assertEqual(result['selected_count'],0)
        self.assertEqual(result['scanned'],1)
        self.assertEqual(result['last_scanned_id'],1)

    def test_empty(self):
        self.assertEqual(choose_batch([],limit=3,after_id=55)['last_scanned_id'],55)

    def test_cursor_scope(self):
        with self.assertRaises(ValueError):choose_batch([(2,'work','ready')],limit=1,after_id=2)

    def test_duplicate_ids(self):
        with self.assertRaises(ValueError):choose_batch([(1,'work','ready'),(1,'work','ready')],limit=3)

    def test_unsorted_ids(self):
        with self.assertRaises(ValueError):choose_batch([(3,'work','ready'),(2,'work','ready')],limit=3)

    def test_excludes_unvalidated_kind(self):
        with self.assertRaises(ValueError):choose_batch([(1,'fake','ready')],limit=3)

    def test_unsafe_exception_redacted(self):
        self.assertEqual(sanitized_failure_code(RuntimeError('raw private story: abc')), 'RuntimeError')

    def test_safe_external_error_code(self):
        self.assertEqual(sanitized_failure_code(RuntimeError('ANTHROPIC_HTTP_503')), 'ANTHROPIC_HTTP_503')


if __name__ == '__main__':unittest.main()
