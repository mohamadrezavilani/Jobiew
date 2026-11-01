"""Pure validator regression tests; run without Django or a database."""
import json
import unittest
from pathlib import Path
from .five_criteria_contract import KEYS, InvalidFiveCriteria, validate_annotations

class ContractTests(unittest.TestCase):
    def good(self):
        return {'dimensions': {key: {'score': None,
              'confidence_evidence_support_unvalidated': 0,
              'evidence':'', 'status':'NO_EVIDENCE_OR_EXCLUDED'} for key in KEYS}}

    def test_exact_five_required(self):
        good = self.good()
        self.assertEqual(len(validate_annotations(good)),5)
        good['dimensions']['workload']={'score':6}
        with self.assertRaises(InvalidFiveCriteria):validate_annotations(good)

    def test_zeros_are_not_scores(self):
        row=self.good();row['dimensions'][KEYS[0]]['score']=0
        with self.assertRaises(InvalidFiveCriteria):validate_annotations(row)

    def test_boolean_scores_rejected(self):
        row=self.good();row['dimensions'][KEYS[0]]['score']=True
        with self.assertRaises(InvalidFiveCriteria):validate_annotations(row)

    def test_scored_requires_evidence(self):
        row=self.good();row['dimensions'][KEYS[0]]['score']=8
        with self.assertRaises(InvalidFiveCriteria):validate_annotations(row)

    def test_abstention_confidence_zero(self):
        row=self.good();row['dimensions'][KEYS[0]]['confidence_evidence_support_unvalidated']=70
        with self.assertRaises(InvalidFiveCriteria):validate_annotations(row)

    def test_confidence_not_probability(self):
        row=self.good();row['dimensions'][KEYS[0]].update({'score':8,'confidence_evidence_support_unvalidated':70,'evidence':'دلیل'})
        self.assertEqual(validate_annotations(row)[KEYS[0]]['confidence'],70)

if __name__=='__main__': unittest.main()
