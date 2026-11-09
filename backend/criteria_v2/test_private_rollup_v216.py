"""Pure tests of fail-closed provisional work/interview aggregation."""
import unittest
from .private_rollup_v216 import aggregate_pilot
from .registry import axes_for


def dimensions(kind, first=None):
    keys=[a.key for a in axes_for(kind)]
    return {key:(first if i==0 else None) for i,key in enumerate(keys)}


class RollupV216PureTests(unittest.TestCase):
    def test_null_is_not_zero(self):
        result=aggregate_pilot('work',total_experiences=30,
                               candidates=[(1,True,dimensions('work',2)),
                                           (2,True,dimensions('work'))])
        self.assertEqual(result['axes'][0]['score'],2)
        self.assertEqual(result['axes'][0]['dimension_experience_count'],1)
        self.assertEqual(result['pilot_abstentions'],11)
        self.assertFalse(result['approved_for_publication'])

    def test_no_cross_kind(self):
        result=aggregate_pilot('interview',total_experiences=1,
                               candidates=[(1,True,dimensions('interview',9))])
        self.assertEqual(result['axes'][0]['score'],9)
        self.assertEqual(len(result['axes']),6)
        self.assertEqual(result['source_kind'],'interview')

    def test_invalid_not_counted(self):
        result=aggregate_pilot('work',total_experiences=2,
                               candidates=[(1,False,dimensions('work',2))])
        self.assertFalse(result['has_scores'])
        self.assertEqual(result['pilot_invalid_cases'],1)

    def test_duplicate_first_wins_even_if_invalid(self):
        result=aggregate_pilot('work',total_experiences=2,
                               candidates=[(1,False,{}),(1,True,dimensions('work',10))])
        self.assertEqual(result['pilot_duplicate_runs'],1)
        self.assertFalse(result['has_scores'])

    def test_duplicate_valid_counts_once(self):
        result=aggregate_pilot('work',total_experiences=2,
                               candidates=[(1,True,dimensions('work',1)),
                                           (1,True,dimensions('work',10))])
        self.assertEqual(result['axes'][0]['score'],1)
        self.assertEqual(result['axes'][0]['dimension_experience_count'],1)

    def test_incomplete_dimensions_excluded(self):
        result=aggregate_pilot('work',total_experiences=2,
                               candidates=[(1,True,{'work_compensation_fairness':9})])
        self.assertEqual(result['pilot_invalid_cases'],1)

    def test_invalid_score_excluded(self):
        bad=dimensions('work',True)
        result=aggregate_pilot('work',total_experiences=2,candidates=[(1,True,bad)])
        self.assertEqual(result['pilot_invalid_cases'],1)

    def test_sufficient_is_only_provisional(self):
        rows=[(i,True,dimensions('work',5)) for i in range(1,7)]
        result=aggregate_pilot('work',total_experiences=6,candidates=rows)
        self.assertEqual(result['axes'][0]['data_sufficiency_status'],'sufficient')
        self.assertFalse(result['approved_for_publication'])

    def test_empty_company(self):
        result=aggregate_pilot('interview',total_experiences=0,candidates=[])
        self.assertEqual(result['pilot_valid_cases'],0)
        self.assertTrue(all(a['score'] is None for a in result['axes']))

    def test_cross_kind_dimensions_rejected(self):
        result=aggregate_pilot('work',total_experiences=1,
                               candidates=[(1,True,dimensions('interview',7))])
        self.assertEqual(result['pilot_invalid_cases'],1)

    def test_invalid_id_rejected(self):
        with self.assertRaises(ValueError):
            aggregate_pilot('work',total_experiences=1,
                           candidates=[(True,True,dimensions('work',7))])

if __name__ == '__main__':unittest.main()
