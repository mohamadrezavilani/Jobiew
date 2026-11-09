"""Regression: invalid model quotes must not inflate benchmark agreement."""
import unittest
from .test_quality_v210 import example, corpus
from .quality_v210 import evaluate
from .registry import axes_for


class QualityFailClosedV211(unittest.TestCase):
    def test_invalid_quote_not_counted_as_mae_success(self):
        row=example()
        key=axes_for('work')[0].key
        row['prediction']['dimensions'][key]['evidence']='این نقل قول ساختگی است و در متن تجربه وجود ندارد'
        r=evaluate(corpus(row))
        self.assertEqual(r['invalid_evidence_or_confidence_axes'],1)
        self.assertIsNone(r['metrics']['score_mae_when_both_scored'])
        self.assertEqual(r['metrics']['scoring_decision_precision'],0)
        self.assertEqual(r['metrics']['scoring_decision_recall'],0)

    def test_wrong_kind_not_inflating_agreement(self):
        row=example()
        row['prediction']['detected_kind']='interview'
        r=evaluate(corpus(row))
        self.assertIsNone(r['metrics']['score_mae_when_both_scored'])
        self.assertEqual(r['metrics']['scoring_decision_precision'],0)

    def test_low_kind_confidence_not_inflating_agreement(self):
        row=example()
        row['prediction']['kind_confidence']=60
        r=evaluate(corpus(row))
        self.assertIsNone(r['metrics']['score_mae_when_both_scored'])
        self.assertEqual(r['metrics']['scoring_decision_precision'],0)

    def test_valid_quote_still_counts(self):
        r=evaluate(corpus(example()))
        self.assertEqual(r['metrics']['score_mae_when_both_scored'],0)
        self.assertEqual(r['metrics']['scoring_decision_recall'],1)

if __name__=='__main__':unittest.main()
