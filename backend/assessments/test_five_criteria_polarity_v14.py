"""v14 scoring-direction contract and label consistency."""
from django.test import SimpleTestCase
from assessments.five_criteria_contract import KEYS, validate_annotations
from assessments.five_criteria_polarity_v14 import (
    FIRST_LABEL, FIRST_KEY, DIRECTION, HIGH_MEANS_BETTER, audit_direction,
)
from assessments.five_criteria_company_v7 import LABELS
from assessments.models import DIMENSIONS, AiDimension, RatingSnapshot

class DirectionContractTests(SimpleTestCase):
    def test_five_axes_are_benefit_oriented(self):
        self.assertEqual(set(KEYS),set(DIRECTION))
        self.assertTrue(HIGH_MEANS_BETTER)
        self.assertEqual(set(DIRECTION.values()), {'HIGH_IS_GOOD'})
    def test_first_label_positive_and_same_everywhere(self):
        self.assertEqual(LABELS[FIRST_KEY],FIRST_LABEL)
        self.assertIn((FIRST_KEY,FIRST_LABEL),DIMENSIONS)
        self.assertEqual(dict(AiDimension._meta.get_field('key').flatchoices)[FIRST_KEY],FIRST_LABEL)
        self.assertEqual(dict(RatingSnapshot._meta.get_field('dimension').flatchoices)[FIRST_KEY],FIRST_LABEL)
    def test_original_key_remains_stable(self):
        self.assertEqual(KEYS[0],FIRST_KEY)
    def test_low_score_with_high_pressure_not_inverted(self):
        self.assertEqual(audit_direction(2,'فشار کاری بالا'),'DIRECTION_CONSISTENT_EXPLICIT_SIGNAL')
    def test_high_score_with_manageable_workload_not_inverted(self):
        self.assertEqual(audit_direction(8,'حجم کار معقول'),'DIRECTION_CONSISTENT_EXPLICIT_SIGNAL')
    def test_high_score_with_high_pressure_is_review_flag(self):
        self.assertEqual(audit_direction(9,'فشار کاری بالا'),'POTENTIAL_REVERSED_POLARITY_REVIEW')
    def test_low_score_with_good_conditions_is_review_flag(self):
        self.assertEqual(audit_direction(1,'ساعت کاری شناور'),'POTENTIAL_REVERSED_POLARITY_REVIEW')
    def test_abstain_no_polarity(self):
        self.assertEqual(audit_direction(None,''),'ABSTAIN')
    def test_no_signal_is_not_auto_corrected(self):
        self.assertEqual(audit_direction(6,'اطلاعاتی ارائه نشده'),'NO_EXPLICIT_POLARITY_SIGNAL')
    def test_score_contract_still_has_five_keys(self):
        dims={key:{'score':None,'confidence_evidence_support_unvalidated':0,'evidence':''} for key in KEYS}
        dims[FIRST_KEY]={'score':8,'confidence_evidence_support_unvalidated':75,'evidence':'حجم کار معقول'}
        self.assertEqual(validate_annotations({'dimensions':dims})[FIRST_KEY]['score'],8)
