"""Pure MVP data-sufficiency acceptance; no database or external API required."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from criteria_v2.sufficiency_contract_v208 import make_sufficiency, MIN_SUFFICIENT_EXPERIENCES
from criteria_v2.registry import axes_for


class MVPPolicyTests(unittest.TestCase):
    def key(self, kind='work', position=0):
        return axes_for(kind)[position].key

    def make(self, kind='work', rows=(), total=12, threshold=6):
        return make_sufficiency(kind, total, rows, threshold=threshold)

    def test_default_threshold_six(self):
        self.assertEqual(MIN_SUFFICIENT_EXPERIENCES, 6)

    def test_zero_means_no_score_not_zero(self):
        a = self.make()['axes'][0]
        self.assertEqual(a['dimension_experience_count'], 0)
        self.assertIsNone(a['score'])
        self.assertEqual(a['data_sufficiency_status'], 'insufficient')

    def test_one_is_partial_but_visible(self):
        a = self.make(rows=[(1,self.key(),2)])['axes'][0]
        self.assertEqual((a['score'],a['data_sufficiency_status']), (2.0,'partial'))

    def test_five_is_partial(self):
        rows = [(i,self.key(),6) for i in range(1,6)]
        a = self.make(rows=rows)['axes'][0]
        self.assertEqual((a['dimension_experience_count'],a['data_sufficiency_status']), (5,'partial'))

    def test_six_is_sufficient(self):
        rows = [(i,self.key(),6) for i in range(1,7)]
        a = self.make(rows=rows)['axes'][0]
        self.assertEqual((a['score'],a['data_sufficiency_status']), (6.0,'sufficient'))

    def test_multiple_dimensions_per_experience(self):
        rows = [(1,self.key(position=0),3),(1,self.key(position=2),8)]
        v = self.make(rows=rows,total=1)
        self.assertEqual(v['axes'][0]['dimension_experience_count'],1)
        self.assertEqual(v['axes'][2]['dimension_experience_count'],1)
        self.assertEqual(sum(x['dimension_experience_count'] for x in v['axes']),2)
        self.assertFalse(v['full_coverage'])

    def test_duplicate_same_experience_axis_only_counts_once(self):
        k=self.key(); a=self.make(rows=[(1,k,3),(1,k,3),(1,k,3)])['axes'][0]
        self.assertEqual((a['dimension_experience_count'],a['score']), (1,3.0))

    def test_conflicting_duplicates_fail_closed(self):
        with self.assertRaises(ValueError):
            self.make(rows=[(1,self.key(),3),(1,self.key(),8)])

    def test_mention_only_abstention_not_counted(self):
        a=self.make(rows=[(1,self.key(),None)])['axes'][0]
        self.assertEqual(a['dimension_experience_count'],0)

    def test_low_score_is_not_absent(self):
        a=self.make(rows=[(1,self.key(),1)])['axes'][0]
        self.assertEqual(a['score'],1.0)
        self.assertIsNotNone(a['chart_x'])

    def test_full_coverage_with_only_partial_data(self):
        rows=[(1,a.key,5) for a in axes_for('work')]
        v=self.make(rows=rows,total=1)
        self.assertTrue(v['full_coverage'])
        self.assertFalse(v['all_sufficient'])
        self.assertEqual(len(v['polygon_points'].split()),6)

    def test_missing_axis_never_filled_as_zero_polygon(self):
        v=self.make(rows=[(1,self.key(),5)])
        self.assertFalse(v['full_coverage'])
        self.assertEqual(v['polygon_points'],'')

    def test_independent_scope_rejects_cross_kind_axis(self):
        with self.assertRaises(ValueError):
            self.make('work',[(1,self.key('interview'),5)])
        self.assertEqual(self.make('interview',[(1,self.key('interview'),5)])['axes'][0]['score'],5.0)

    def test_total_experiences_does_not_drive_sufficiency(self):
        v=self.make(total=100000,rows=[(1,self.key(),5)])
        self.assertEqual(v['axes'][0]['data_sufficiency_status'],'partial')
        self.assertEqual(v['total_experiences'],100000)

    def test_threshold_is_configurable(self):
        rows=[(1,self.key(),5),(2,self.key(),7)]
        self.assertEqual(self.make(rows=rows,threshold=2)['axes'][0]['data_sufficiency_status'],'sufficient')
        self.assertEqual(self.make(rows=rows,threshold=3)['axes'][0]['data_sufficiency_status'],'partial')

    def test_invalid_threshold_or_score_rejected(self):
        for t in (None,0,1,True,1.5,'6',1001):
            with self.subTest(t=t), self.assertRaises(ValueError):self.make(threshold=t)
        for v in (True,0,11,2.5,'5'):
            with self.subTest(v=v), self.assertRaises(ValueError):self.make(rows=[(1,self.key(),v)])

    def test_mean_uses_one_equal_vote_per_experience(self):
        a=self.make(rows=[(1,self.key(),1),(2,self.key(),10)])['axes'][0]
        self.assertEqual(a['score'],5.5)

    def test_negative_total_rejected(self):
        with self.assertRaises(ValueError):self.make(total=-1)


if __name__ == '__main__':
    unittest.main()
