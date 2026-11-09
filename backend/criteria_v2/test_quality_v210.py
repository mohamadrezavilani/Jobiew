"""Offline benchmark invariants; deliberately synthetic, no paid API or database."""
import copy
import unittest
from .quality_v210 import BENCHMARK_VERSION, BenchmarkError, evaluate
from .registry import axes_for

WORK_STORY = ('پنج ماه حقوق ما را بدون اطلاع قبلی با تأخیر پرداخت کردند. '
              'مدیر مستقیم در جلسات محترمانه برخورد می‌کرد و گفتگو باز بود.')
INTERVIEW_STORY = ('در جلسه مصاحبه سوالات مرتبط با مهارت فنی پرسیده شد. '
                   'پس از مصاحبه نتیجه را در زمان تعیین شده اعلام کردند.')


def example(kind='work', index='001', *, scored=True):
    story = WORK_STORY if kind == 'work' else INTERVIEW_STORY
    quote = 'پنج ماه حقوق ما را بدون اطلاع قبلی با تأخیر پرداخت کردند' if kind == 'work' else 'در جلسه مصاحبه سوالات مرتبط با مهارت فنی پرسیده شد'
    score = 2 if kind == 'work' else 8
    names = [a.key for a in axes_for(kind)]
    return {'case_id':f'{kind}-{index}', 'kind':kind, 'story':story,
            'gold': {k:{'score':score if scored and i == 0 else None,
                        'evidence':quote if scored and i == 0 else ''} for i,k in enumerate(names)},
            'prediction': {'detected_kind':kind, 'kind_confidence':98,
                 'dimensions': {k:{'score':score if scored and i == 0 else None,
                                   'confidence':94 if scored and i == 0 else 0,
                                   'evidence':quote if scored and i == 0 else '',
                                   'explanation':'توضیح روشن درباره دادهٔ موجود یا امتناع به دلیل نبود شاهد'}
                                for i,k in enumerate(names)}}}


def corpus(*cases):
    return {'benchmark_version': BENCHMARK_VERSION, 'cases':list(cases)}


class OfflineBenchmarkTests(unittest.TestCase):
    def test_same_scoring(self):
        r = evaluate(corpus(example()))
        self.assertEqual(r['metrics']['score_mae_when_both_scored'],0)
        self.assertEqual(r['metrics']['scoring_decision_precision'],1)
        self.assertFalse(r['release_approved'])

    def test_both_scopes_are_independent(self):
        r = evaluate(corpus(example(),example('interview')))
        self.assertEqual(r['cases_by_kind'],{'work':1,'interview':1})
        self.assertEqual(len(r['per_axis']),12)

    def test_no_score_is_not_zero(self):
        r = evaluate(corpus(example(scored=False)))
        self.assertIsNone(r['metrics']['score_mae_when_both_scored'])
        self.assertEqual(r['metrics']['reference_scored_axes'],0)

    def test_score_difference(self):
        c=example(); k=axes_for('work')[0].key
        c['prediction']['dimensions'][k]['score']=7
        r=evaluate(corpus(c))
        self.assertEqual(r['metrics']['score_mae_when_both_scored'],5)
        self.assertEqual(r['metrics']['score_within_one_when_both_scored'],0)

    def test_prediction_abstention(self):
        c=example(); k=axes_for('work')[0].key
        c['prediction']['dimensions'][k].update(score=None,confidence=0,evidence='')
        r=evaluate(corpus(c))
        self.assertIsNone(r['metrics']['score_mae_when_both_scored'])
        self.assertEqual(r['metrics']['scoring_decision_recall'],0)

    def test_prediction_hallucinated_scoring(self):
        c=example(scored=False);k=axes_for('work')[1].key
        c['prediction']['dimensions'][k].update(score=9,confidence=99,evidence='مدیر مستقیم در جلسات محترمانه برخورد می‌کرد')
        r=evaluate(corpus(c))
        self.assertEqual(r['metrics']['scoring_decision_precision'],0)

    def test_predicted_kind_disagreement(self):
        c=example();c['prediction']['detected_kind']='interview'
        self.assertEqual(evaluate(corpus(c))['kind_disagreement_cases'],1)

    def test_invalid_model_quote_is_flagged_not_silently_accepted(self):
        c=example();k=axes_for('work')[0].key
        c['prediction']['dimensions'][k]['evidence']='این نقل قول در اصل وجود ندارد و ساختگی است'
        self.assertEqual(evaluate(corpus(c))['invalid_evidence_or_confidence_axes'],1)

    def test_confidence_below_threshold_flagged(self):
        c=example();k=axes_for('work')[0].key
        c['prediction']['dimensions'][k]['confidence']=69
        self.assertEqual(evaluate(corpus(c))['invalid_evidence_or_confidence_axes'],1)

    def test_invalid_gold_quote_fails(self):
        c=example();k=axes_for('work')[0].key
        c['gold'][k]['evidence']='شاهد جعلی و فاقد انطباق در روایت مرجع'
        with self.assertRaises(BenchmarkError): evaluate(corpus(c))

    def test_wrong_scope_axis_fails(self):
        c=example();k=axes_for('work')[0].key
        c['prediction']['dimensions']['interview_quality_fairness']=c['prediction']['dimensions'].pop(k)
        with self.assertRaises(BenchmarkError): evaluate(corpus(c))

    def test_duplicate_id_fails(self):
        c=example()
        with self.assertRaises(BenchmarkError): evaluate(corpus(c,copy.deepcopy(c)))

    def test_wrong_version_fails(self):
        c=corpus(example());c['benchmark_version']='five_v1'
        with self.assertRaises(BenchmarkError): evaluate(c)

    def test_float_score_rejected(self):
        c=example();k=axes_for('work')[0].key
        c['prediction']['dimensions'][k]['score']=7.0
        with self.assertRaises(BenchmarkError): evaluate(corpus(c))

    def test_bool_score_rejected(self):
        c=example();k=axes_for('work')[0].key
        c['gold'][k]['score']=True
        with self.assertRaises(BenchmarkError): evaluate(corpus(c))

    def test_null_with_nonzero_confidence_flags(self):
        c=example(scored=False);k=axes_for('work')[0].key
        c['prediction']['dimensions'][k]['confidence']=70
        self.assertEqual(evaluate(corpus(c))['invalid_evidence_or_confidence_axes'],1)

    def test_empty_corpus_fails(self):
        with self.assertRaises(BenchmarkError): evaluate(corpus())

    def test_input_requires_all_six_axes(self):
        c=example();k=axes_for('work')[2].key
        del c['gold'][k]
        with self.assertRaises(BenchmarkError): evaluate(corpus(c))

    def test_no_raw_story_leak_in_report(self):
        r=evaluate(corpus(example()))
        self.assertNotIn('پنج ماه حقوق',str(r))

    def test_multiple_cases_independent(self):
        c=example();d=example(index='002')
        k=axes_for('work')[0].key
        d['prediction']['dimensions'][k]['score']=4
        r=evaluate(corpus(c,d))
        self.assertEqual(r['metrics']['score_mae_when_both_scored'],1)
        self.assertEqual(r['cases_by_kind']['work'],2)

if __name__=='__main__':
    unittest.main()
