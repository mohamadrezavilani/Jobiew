"""No Django required for pure provisional summary tests (also discovered by Django)."""
from django.test import SimpleTestCase
from .five_criteria_provisional_v11 import provisional_company_aggregate

class PrivateProvisionalSummaryTests(SimpleTestCase):
    def row(self,exp,score,key='work_conditions_pressure',hash_value=None):
        return {'company_id':'A','experience_id':str(exp),'dimension':key,
                'score':score,'content_hash':hash_value or str(exp)*64}

    def test_average_and_abstentions(self):
        x=provisional_company_aggregate('A',[self.row(1,2),self.row(2,8),self.row(3,None)])
        m=x['criteria']['work_conditions_pressure']
        self.assertEqual(m['mean_provisional'],5)
        self.assertEqual(m['n_provisional_used'],2)
        self.assertEqual(m['n_provisional_abstentions'],1)
        self.assertEqual(x['publication_status'],'NOT_APPROVED_FOR_PUBLICATION')

    def test_mixed_companies_blocked(self):
        bad=self.row(1,8);bad['company_id']='B'
        with self.assertRaises(ValueError):provisional_company_aggregate('A',[bad])

    def test_duplicate_runs_are_excluded_not_averaged(self):
        x=provisional_company_aggregate('A',[self.row(1,1),self.row(1,9),self.row(2,8)])
        m=x['criteria']['work_conditions_pressure']
        self.assertEqual(m['mean_provisional'],8)
        self.assertEqual(m['n_ambiguous_run_rows'],2)

    def test_duplicate_text_with_different_experience_id(self):
        a=self.row(1,2,hash_value='abcdef'*10+'abcd')
        b=self.row(2,8,hash_value='abcdef'*10+'abcd')
        x=provisional_company_aggregate('A',[a,b])['criteria']['work_conditions_pressure']
        self.assertEqual(x['n_provisional_used'],1)
        self.assertEqual(x['n_content_duplicates_excluded'],1)

    def test_missing_and_invalid_scores(self):
        self.assertIsNone(provisional_company_aggregate('A',[])['criteria']['growth_development']['mean_provisional'])
        with self.assertRaises(ValueError):provisional_company_aggregate('A',[self.row(1,True)])
        with self.assertRaises(ValueError):provisional_company_aggregate('A',[self.row(1,11)])

    def test_insufficient_one_kept_as_provisional_not_verified(self):
        x=provisional_company_aggregate('A',[self.row(1,7)])['criteria']['work_conditions_pressure']
        self.assertEqual(x['mean_provisional'],7)
        self.assertEqual(x['n_provisional_used'],1)
        self.assertEqual(x['status'],'UNREVIEWED_AI_RESEARCH_ONLY')
