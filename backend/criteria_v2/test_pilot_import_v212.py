"""Pure, offline guardrail checks. No database or external API."""
import copy
import unittest
from .pilot_import_v212 import (
    PilotImportError, PILOT_VERSION, load_private_bundle,
    aggregate_report, deterministic_run_id,
)
from .registry import axes_for

STORY = ('در تمام این مدت شرکت حقوق من را با تاخیر دو ماه پرداخت می کرد '
         'و مدیر در پاسخ به اعتراض من توضیح واضحی نمی داد.')
QUOTE = 'شرکت حقوق من را با تاخیر دو ماه پرداخت می کرد'


def fixture():
    kind = 'work'
    axes = axes_for(kind)
    dims = {a.key:{'score':None,'confidence':0,'evidence':'',
                     'explanation':'برای ارزیابی این بُعد شاهد مستقیمی در روایت وجود ندارد'}
            for a in axes}
    dims[axes[0].key] = {'score':2,'confidence':90,'evidence':QUOTE,
                         'explanation':'پرداخت حقوق با تأخیر دوماهه نشان‌دهنده ضعف در پرداخت است'}
    story = {'pilot_version':PILOT_VERSION,'cases':[
        {'case_id':'work-001','kind':kind,'story':STORY}]}
    mapping = {'pilot_version':PILOT_VERSION,'cases':[
        {'case_id':'work-001','source_experience_id':101,'length_group':'short'}]}
    pred = {'pilot_version':PILOT_VERSION,'cases':[
        {'case_id':'work-001','prediction':{'detected_kind':kind,'kind_confidence':91,
          'dimensions':dims}}]}
    return story, mapping, pred


class PilotImportPureTests(unittest.TestCase):
    def test_valid_one_case_and_summary_no_text(self):
        rows = load_private_bundle(*fixture())
        self.assertEqual(rows[0]['dimensions'][axes_for('work')[0].key]['score'],2)
        self.assertEqual(rows[0]['dimensions'][axes_for('work')[0].key]['evidence'],[QUOTE])
        report = aggregate_report(rows)
        self.assertEqual(report['numeric_proposals'],1)
        self.assertEqual(report['abstentions'],5)
        self.assertEqual(report['human_reference'],'NOT_INDEPENDENT')
        self.assertNotIn(STORY,str(report))

    def test_deterministic_run_id(self):
        row=load_private_bundle(*fixture())[0]
        x=deterministic_run_id(row,'a'*64)
        self.assertEqual(x,deterministic_run_id(row,'a'*64))
        self.assertNotEqual(x,deterministic_run_id(row,'b'*64))
        self.assertLessEqual(len(x),120)

    def test_duplicate_source_id_is_rejected(self):
        s,m,p=fixture()
        s['cases'].append({**s['cases'][0], 'case_id':'work-002'})
        p['cases'].append({**p['cases'][0], 'case_id':'work-002'})
        m['cases'].append({**m['cases'][0], 'case_id':'work-002'})
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_incomplete_six_axes_rejected(self):
        s,m,p=fixture()
        del p['cases'][0]['prediction']['dimensions'][axes_for('work')[1].key]
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_mismatched_case_ids_rejected(self):
        s,m,p=fixture()
        m['cases'][0]['case_id']='work-002'
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_invalid_quote_rejected(self):
        s,m,p=fixture()
        p['cases'][0]['prediction']['dimensions'][axes_for('work')[0].key]['evidence']='اینجا اصلا چنین عبارتی در متن وجود ندارد'
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_null_with_evidence_rejected(self):
        s,m,p=fixture()
        p['cases'][0]['prediction']['dimensions'][axes_for('work')[1].key]['evidence']='شاهد ساختگی غلط برای امتناع'
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_kind_mismatch_rejected(self):
        s,m,p=fixture()
        p['cases'][0]['prediction']['detected_kind']='interview'
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_wrong_scope_rejected(self):
        s,m,p=fixture()
        p['cases'][0]['prediction']['dimensions']['interview_professional_respect']=p['cases'][0]['prediction']['dimensions'].pop(axes_for('work')[0].key)
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_no_predictions_rejected(self):
        s,m,p=fixture()
        p['cases'][0]['prediction']=None
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_empty_input_rejected(self):
        s,m,p=fixture()
        for x in (s,m,p):x['cases']=[]
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

    def test_boolean_id_rejected(self):
        s,m,p=fixture()
        m['cases'][0]['source_experience_id']=True
        with self.assertRaises(PilotImportError):load_private_bundle(s,m,p)

if __name__ == '__main__':unittest.main()
