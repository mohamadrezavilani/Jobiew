"""Pure aggregation tests: no Django/database/external API required."""
import unittest
from .five_criteria_aggregation import research_aggregate


class ResearchAggregationTests(unittest.TestCase):
    def item(self, exp, score, **kwargs):
        return dict(experience_id=exp, dimension='work_conditions_pressure', score=score,
                    human_verified=True, rights_verified=True,
                    attribution_verified=True, independence_verified=True, **kwargs)

    def test_requires_three_gated_independent_reviews(self):
        result=research_aggregate([self.item('1',4),self.item('2',6)])
        self.assertIsNone(result['criteria']['work_conditions_pressure']['mean_diagnostic'])
        self.assertEqual(result['publication_status'],'NOT_APPROVED_FOR_PUBLICATION')

    def test_mean_diagnostic_not_public(self):
        result=research_aggregate([self.item('1',4),self.item('2',6),self.item('3',8)])
        self.assertEqual(result['criteria']['work_conditions_pressure']['mean_diagnostic'],6)
        self.assertEqual(result['publication_status'],'NOT_APPROVED_FOR_PUBLICATION')

    def test_duplicate_reruns_are_not_independent(self):
        result=research_aggregate([self.item('1',4),self.item('1',6),self.item('2',6),self.item('3',8)])
        self.assertEqual(result['criteria']['work_conditions_pressure']['n_verified_independent'],2)

    def test_unverified_suppressed(self):
        bad=self.item('3',8)
        bad['rights_verified']=False
        result=research_aggregate([self.item('1',4),self.item('2',6),bad])
        self.assertIsNone(result['criteria']['work_conditions_pressure']['mean_diagnostic'])

    def test_no_lower_minimum(self):
        with self.assertRaises(ValueError):research_aggregate([],min_independent=1)

if __name__=='__main__':unittest.main()
