"""Pure tests for privacy-preserving deterministic semantic review sampling."""
import unittest
from .checkpoint_sampling_v218 import sample_semantic_review


class SamplingV218Tests(unittest.TestCase):
    @staticmethod
    def input():
        axis = 'work_compensation_fairness'
        rows = [
            {'experience_id': i, 'company_id': i % 3, 'kind': 'work',
             'prediction': {'dimensions': {axis: {'score': None if i % 2 else 6}}}}
            for i in range(1, 21)]
        ledger = {i: {} for i in range(1, 21)}
        ledger[20]['exact_duplicate_of_experience_id'] = 2
        return rows, ledger

    def test_reproducible_blind_samples_no_scores_or_stories(self):
        rows, ledger = self.input()
        a, ac = sample_semantic_review(rows, ledger, each=3)
        b, bc = sample_semantic_review(rows, ledger, each=3)
        self.assertEqual(a, b)
        self.assertEqual(ac, bc)
        self.assertEqual(len(a), 6)
        self.assertNotIn(20, [x['experience_id'] for x in a])
        self.assertNotIn('prediction', str(a))
        self.assertTrue(all(x['blind_score'] is None for x in a))

    def test_invalid_stratum_limit_refused(self):
        rows, ledger = self.input()
        with self.assertRaises(ValueError):
            sample_semantic_review(rows, ledger, each=0)
        with self.assertRaises(ValueError):
            sample_semantic_review(rows, ledger, each=51)


if __name__ == '__main__':
    unittest.main()
