"""Offline, stdlib-only regressions; no Django, database, network, or API key needed."""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(ROOT))

from criteria_v2.engine_v207 import (
    ProposalError, build_request, call_claude, response_schema, safe_usage,
    story_digest, story_from_experience, validate_response,
)
from criteria_v2.registry import AXES

STORY = ('متن تجربه:\nحقوق همیشه با دو ماه تأخیر پرداخت می‌شد و مدیر درباره پرداخت‌ها '
         'هیچ توضیحی نمی‌داد، اما تیم از نظر فنی فرصت یادگیری مناسبی داشت.')
QUOTE = 'حقوق همیشه با دو ماه تأخیر پرداخت می‌شد'


def sample(kind='work'):
    axes = AXES[kind]
    dims = {a.key: {'score': None, 'confidence': 0, 'evidence': '',
                    'explanation': 'شواهد مستقیمی برای این شاخص وجود ندارد'} for a in axes}
    return {'detected_kind': kind, 'kind_confidence': 90, 'dimensions': dims}


def api_response(payload, stop='end_turn'):
    return {'stop_reason': stop, 'content': [{'type': 'text',
            'text': json.dumps(payload, ensure_ascii=False)}],
            'usage': {'input_tokens': 150, 'output_tokens': 90}}


class EngineContractTests(unittest.TestCase):
    def test_twelve_distinct_axes(self):
        self.assertEqual(len(AXES['work']), 6)
        self.assertEqual(len(AXES['interview']), 6)
        self.assertFalse({a.key for a in AXES['work']} & {a.key for a in AXES['interview']})

    def test_schema_exact_scope(self):
        schema = response_schema('interview')
        self.assertEqual(set(schema['properties']['dimensions']['properties']),
                         {a.key for a in AXES['interview']})
        self.assertFalse(schema['additionalProperties'])

    def test_story_drops_source_identity_and_redacts_pii(self):
        exp = SimpleNamespace(body='تماس 09123456789 و a@b.com و شماره 123456789012',
                              pros=['حقوق به موقع پرداخت شد'], cons=[],
                              source_url='https://secret.invalid', company_id='private')
        story = story_from_experience(exp)
        self.assertNotIn('09123456789', story)
        self.assertNotIn('a@b.com', story)
        self.assertNotIn('123456789012', story)
        self.assertNotIn('https://secret.invalid', story)
        self.assertIn('[phone]', story)
        self.assertIn('[email]', story)
        self.assertEqual(story_digest(story), story_digest(story))

    def test_prompt_includes_scope_and_untrusted_delimiter(self):
        body = build_request('work', STORY, 'claude-sonnet-4-6')
        self.assertEqual(body['output_config']['format']['type'], 'json_schema')
        self.assertIn('<untrusted_story>', body['messages'][0]['content'])
        self.assertNotIn('interview_quality_fairness', body['messages'][0]['content'])

    def test_invalid_model_rejected(self):
        with self.assertRaises(ValueError):
            build_request('work', STORY, 'not-a-model')

    def test_too_short_story_rejected(self):
        with self.assertRaises(ProposalError):
            build_request('work', 'کوتاه', 'claude-sonnet-4-6')

    def test_valid_abstentions(self):
        result = validate_response(api_response(sample()), kind='work', story=STORY)
        self.assertEqual(result['status'], 'unreviewed')
        self.assertEqual(len(result['dimensions']), 6)
        self.assertTrue(all(x['score'] is None for x in result['dimensions'].values()))

    def test_evidence_backed_negative_score(self):
        p = sample()
        p['dimensions']['work_compensation_fairness'] = {
            'score': 2, 'confidence': 91, 'evidence': QUOTE,
            'explanation': 'تأخیر مستمر در پرداخت حقوق نشانه نامطلوبی است'}
        got = validate_response(api_response(p), kind='work', story=STORY)
        self.assertEqual(got['dimensions']['work_compensation_fairness']['score'], 2)
        self.assertEqual(got['dimensions']['work_compensation_fairness']['evidence'], [QUOTE])

    def test_mismatched_kind_flags_instead_of_scoring(self):
        p = sample('work'); p['detected_kind'] = 'interview'
        got = validate_response(api_response(p), kind='work', story=STORY)
        self.assertEqual(got['status'], 'needs_review')
        self.assertIsNone(got['dimensions'])

    def test_low_kind_confidence_flags(self):
        p = sample('work'); p['kind_confidence'] = 69
        self.assertEqual(validate_response(api_response(p), kind='work', story=STORY)['status'], 'needs_review')

    def test_hallucinated_evidence_blocked(self):
        p = sample()
        p['dimensions']['work_compensation_fairness'] = {
            'score': 8, 'confidence': 99, 'evidence': 'حقوق هر ماه دقیقاً سر وقت واریز می‌شد',
            'explanation': 'ادعای پرداخت منظم در متن وجود دارد'}
        with self.assertRaisesRegex(ProposalError, 'EVIDENCE_NOT_VERBATIM'):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_bool_score_rejected(self):
        p = sample(); p['dimensions']['work_compensation_fairness']['score'] = True
        with self.assertRaises(ProposalError):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_zero_score_rejected(self):
        p = sample(); p['dimensions']['work_compensation_fairness']['score'] = 0
        with self.assertRaises(ProposalError):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_wrong_scope_keys_rejected(self):
        p = sample(); p['dimensions']['interview_quality_fairness'] = p['dimensions'].pop('work_compensation_fairness')
        with self.assertRaises(ProposalError):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_null_with_nonzero_confidence_rejected(self):
        p = sample(); p['dimensions']['work_compensation_fairness']['confidence'] = 20
        with self.assertRaises(ProposalError):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_score_with_low_confidence_rejected(self):
        p = sample(); p['dimensions']['work_compensation_fairness'] = {
            'score': 3, 'confidence': 55, 'evidence': QUOTE,
            'explanation': 'شواهدی درباره تأخیر در پرداخت وجود دارد'}
        with self.assertRaisesRegex(ProposalError, 'LOW_CONFIDENCE'):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_redacted_evidence_rejected(self):
        story = STORY + ' شماره تماس [phone] در متن آمده است'
        p = sample(); p['dimensions']['work_compensation_fairness'] = {
            'score': 3, 'confidence': 85, 'evidence': 'شماره تماس [phone] در متن آمده است',
            'explanation': 'نباید از جایگزین اطلاعات محرمانه شاهد تولید شود'}
        with self.assertRaisesRegex(ProposalError, 'REDACTION'):
            validate_response(api_response(p), kind='work', story=story)

    def test_refusal_or_truncated_response_rejected(self):
        with self.assertRaises(ProposalError):
            validate_response(api_response(sample(), 'max_tokens'), kind='work', story=STORY)

    def test_invalid_json_rejected(self):
        with self.assertRaises(ProposalError):
            validate_response({'stop_reason': 'end_turn', 'content': [{'type':'text','text':'oops'}]},
                              kind='work', story=STORY)

    def test_missing_key_rejected(self):
        p = sample(); p.pop('kind_confidence')
        with self.assertRaises(ProposalError):
            validate_response(api_response(p), kind='work', story=STORY)

    def test_usage_limited_to_numeric_counts(self):
        self.assertEqual(safe_usage({'usage': {'input_tokens': True, 'output_tokens': 30}}),
                         {'output_tokens': 30})

    def test_no_api_key_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'ANTHROPIC_API_KEY_MISSING'):
                call_claude({'model': 'claude-sonnet-4-6'})


if __name__ == '__main__':
    unittest.main()
