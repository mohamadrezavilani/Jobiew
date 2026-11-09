"""Offline synthetic tests: no API, no DB, no filesystem writes."""
import copy
import unittest
from .pilot_v211 import (PilotError, PENDING, PILOT_VERSION, select_cases,
                         make_private_documents, combine_private_documents)
from .registry import axes_for


def candidate(i,kind='work',size=100):
    return {'local_id':i,'kind':kind,'story':('درباره احترام در محیط کار نکته ای روشن بیان شده است. '*100)[:size]}


def labelled_fixture():
    selected=select_cases([candidate(1),candidate(2,'interview')],per_kind=1)
    docs=make_private_documents(selected)
    stories,gold,predictions,mapping=docs
    for row in gold['cases']:
        for value in row['gold'].values():
            value.update(score=None,evidence='')
    for row in predictions['cases']:
        kind=next(x['kind'] for x in stories['cases'] if x['case_id']==row['case_id'])
        row['prediction']={'detected_kind':kind,'kind_confidence':92,
          'dimensions':{x.key:{'score':None,'confidence':0,'evidence':'',
                               'explanation':'در این روایت شواهد کافی برای ارزیابی نیست'}
                        for x in axes_for(kind)}}
    return docs


class PilotV211Tests(unittest.TestCase):
    def test_balanced_selection(self):
        rows=[candidate(i,'work') for i in range(1,15)]+[candidate(i,'interview') for i in range(15,30)]
        result=select_cases(rows,per_kind=5)
        self.assertEqual(sum(x['kind']=='work' for x in result),5)
        self.assertEqual(sum(x['kind']=='interview' for x in result),5)

    def test_deterministic(self):
        rows=[candidate(i) for i in range(1,20)]
        self.assertEqual(select_cases(rows,per_kind=4),select_cases(rows,per_kind=4))

    def test_order_independent(self):
        rows=[candidate(i) for i in range(1,20)]
        self.assertEqual(select_cases(rows,per_kind=5),select_cases(list(reversed(rows)),per_kind=5))

    def test_duplicate_source_rejected(self):
        with self.assertRaises(PilotError):select_cases([candidate(1),candidate(1)])

    def test_invalid_kind_rejected(self):
        with self.assertRaises(PilotError):select_cases([candidate(1,'other')])

    def test_short_or_empty_dropped(self):
        self.assertEqual(select_cases([candidate(1,size=5)]),[])

    def test_unbounded_request_rejected(self):
        with self.assertRaises(PilotError):select_cases([],per_kind=51)

    def test_prepare_separates_blind_human_labels(self):
        docs=make_private_documents(select_cases([candidate(1)]))
        stories,gold,predictions,mapping=docs
        self.assertNotIn('prediction',str(gold))
        self.assertNotIn('story',str(gold))
        self.assertEqual(list(gold['cases'][0]['gold'].values())[0]['score'],PENDING)
        self.assertNotIn('source_experience_id',str(stories))
        self.assertIn('source_experience_id',str(mapping))

    def test_unlabelled_fails_closed(self):
        docs=make_private_documents(select_cases([candidate(1)]))
        with self.assertRaises(PilotError):combine_private_documents(*docs[:3])

    def test_correctly_labelled_assembles(self):
        docs=labelled_fixture()
        c=combine_private_documents(*docs[:3])
        self.assertEqual(len(c['cases']),2)
        self.assertEqual(c['benchmark_version'],'jobiew_dual6_quality_v210')

    def test_missing_prediction_fails(self):
        docs=labelled_fixture()
        docs[2]['cases'][0]['prediction']=None
        with self.assertRaises(PilotError):combine_private_documents(*docs[:3])

    def test_scope_mismatch_fails(self):
        docs=labelled_fixture()
        docs[1]['cases'][0]['kind']='interview'
        with self.assertRaises(PilotError):combine_private_documents(*docs[:3])

    def test_duplicate_case_fails(self):
        docs=labelled_fixture()
        docs[0]['cases'].append(copy.deepcopy(docs[0]['cases'][0]))
        with self.assertRaises(PilotError):combine_private_documents(*docs[:3])

    def test_cross_kind_prediction_fails(self):
        docs=labelled_fixture()
        dims=docs[2]['cases'][0]['prediction']['dimensions']
        dims['wrong_key']=dims.pop(next(iter(dims)))
        with self.assertRaises(PilotError):combine_private_documents(*docs[:3])

    def test_raw_story_not_in_gold(self):
        docs=labelled_fixture()
        self.assertNotIn('درباره احترام',str(docs[1]))


if __name__=='__main__':unittest.main()
