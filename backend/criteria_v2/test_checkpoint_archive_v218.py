"""Synthetic only: archive tampering, checksum coverage, and re-import integrity.
No private text, Django database, or API required.
"""
import hashlib
import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from .checkpoint_qav218 import audit, CheckpointError, html_report
from .checkpoint_contract_v218 import load_handoff, stored_scores_match


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode('utf-8')


def sha(obj):
    return hashlib.sha256(obj).hexdigest()


class ArchiveV218SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.zip'
        self.checkpoint = self.root / 'checkpoint.zip'
        story = 'متن تجربه:\nحقوق هر ماه با دو ماه تأخیر پرداخت می شد و پیگیری نتیجه مشخصی نداشت.'
        self.story = story
        self.exp = {'experience_id': 1, 'company_id': 17, 'source_kind': 'work',
                    'story': story, 'story_length': len(story),
                    'story_sha256': sha(story.encode('utf-8')),
                    'source_content_sha256': 'a' * 64}
        src_data = canonical(self.exp) + b'\n'
        self.source_members = {
            'manifest.json': canonical({
                'format': 'jobiew_chatgpt_dual6_source_export_v1',
                'batches': [{'file': 'batches/batch_0001.jsonl', 'sha256': sha(src_data),
                             'count': 1, 'first_id': 1, 'last_id': 1}],
                'counts': {'all_experiences': 1}}),
            'batches/batch_0001.jsonl': src_data}
        self.write_zip(self.source, self.source_members)
        self.pred = {
            'experience_id': 1, 'company_id': 17, 'kind': 'work',
            'source_content_sha256': 'a' * 64, 'story_sha256': self.exp['story_sha256'],
            'state': 'assistant_reviewed_draft',
            'review_status': 'unverified_private_proposal',
            'prediction': {'detected_kind': 'work', 'kind_confidence': 90,
                           'dimensions': {key: ({'score': 2, 'confidence': 80,
                            'evidence': 'حقوق هر ماه با دو ماه تأخیر پرداخت می شد',
                            'explanation': 'پرداخت با تأخیر به صراحت شرح داده شده است'}
                            if idx == 0 else {'score': None, 'confidence': 0,
                            'evidence': '', 'explanation': 'در متن شواهد کافی وجود ندارد'})
                           for idx, key in enumerate((
                               'work_compensation_fairness', 'work_life_flexibility',
                               'work_growth_career', 'work_management_culture',
                               'work_stability_security', 'work_challenge_autonomy'))}}
        }
        self.ledger = {key: self.pred[key] for key in (
            'experience_id', 'company_id', 'kind', 'source_content_sha256', 'story_sha256')}
        self.ledger['status'] = 'assistant_reviewed_draft'
        self.cp = {'source_archive_sha256': sha(self.source.read_bytes()),
                   'assistant_reviewed_records': 1,
                   'assistant_numeric_axis_proposals': 1,
                   'assistant_null_axis_proposals': 5,
                   'status_counts': {'assistant_reviewed_draft': 1},
                   'resume_next_experience_id': 2,
                   'publication': 'DISABLED', 'source_rights': 'NOT_ESTABLISHED',
                   'independent_semantic_accuracy_established': False}
        self.make_checkpoint()

    @staticmethod
    def write_zip(path, members):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for k, v in members.items():
                z.writestr(k, v)

    def make_checkpoint(self):
        members = {
            'checkpoint.json': canonical(self.cp),
            'ledger.jsonl': canonical(self.ledger) + b'\n',
            'assistant_predictions.jsonl': canonical(self.pred) + b'\n',
            'quality_audit.json': canonical({'validation': 'PASS'}),
        }
        members['files_sha256.json'] = canonical({k: sha(v) for k, v in members.items()})
        self.write_zip(self.checkpoint, members)
        return members

    def test_valid_synthetic_zip_and_html_integer_company_id(self):
        report, companies = audit(self.source, self.checkpoint)
        self.assertEqual(report['validation'], 'PASS')
        self.assertEqual(report['numeric_proposals'], 1)
        self.assertIn('17', html_report(report, companies))
        proposals, ledger, _ = load_handoff(self.source, self.checkpoint)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(len(ledger), 1)

    def test_quote_tamper_fails_even_with_recalculated_member_hash(self):
        self.pred['prediction']['dimensions']['work_compensation_fairness']['evidence'] = 'شاهدی که در متن وجود ندارد و باید رد شود'
        self.make_checkpoint()
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_missing_checksum_manifest_entry_rejected(self):
        members = self.make_checkpoint()
        checks = json.loads(members['files_sha256.json'])
        checks.pop('ledger.jsonl')
        members['files_sha256.json'] = canonical(checks)
        self.write_zip(self.checkpoint, members)
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_unexpected_member_rejected(self):
        members = self.make_checkpoint()
        members['unverified.txt'] = b'not expected'
        self.write_zip(self.checkpoint, members)
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_fake_duplicate_claim_rejected(self):
        self.ledger['exact_duplicate_of_experience_id'] = 1
        self.make_checkpoint()
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_zip_member_count_rejected_before_decompression(self):
        members = self.make_checkpoint()
        for i in range(501):
            members[f'untrusted_{i}.txt'] = b'0'
        self.write_zip(self.checkpoint, members)
        with self.assertRaisesRegex(CheckpointError, 'too many members'):
            load_handoff(self.source, self.checkpoint)

    def test_source_digest_mismatch_rejected(self):
        self.cp['source_archive_sha256'] = 'b' * 64
        self.make_checkpoint()
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_publication_flag_rejected(self):
        self.cp['publication'] = 'ENABLED'
        self.make_checkpoint()
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_duplicate_object_key_rejected(self):
        members = self.make_checkpoint()
        members['quality_audit.json'] = b'{"validation":"PASS","validation":"PASS"}'
        members['files_sha256.json'] = canonical({k: sha(v) for k, v in members.items()
                                                  if k != 'files_sha256.json'})
        self.write_zip(self.checkpoint, members)
        # quality_audit is hash-verified but otherwise not parsed by contract.
        # Duplicate keys in the parsed checkpoint itself MUST be rejected.
        members['checkpoint.json'] = members['checkpoint.json'][:-1] + b',"publication":"DISABLED"}'
        members['files_sha256.json'] = canonical({k: sha(v) for k, v in members.items()
                                                  if k != 'files_sha256.json'})
        self.write_zip(self.checkpoint, members)
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_all_null_six_axis_checkpoint_passes_without_zero(self):
        for item in self.pred['prediction']['dimensions'].values():
            item.update(score=None, confidence=0, evidence='',
                        explanation='در متن هیچ شاهد مستقلی برای این محور موجود نیست')
        self.pred['state'] = 'assistant_reviewed_all_null'
        self.ledger['status'] = 'assistant_reviewed_all_null'
        self.cp['assistant_numeric_axis_proposals'] = 0
        self.cp['assistant_null_axis_proposals'] = 6
        self.cp['status_counts'] = {'assistant_reviewed_all_null': 1}
        self.make_checkpoint()
        report, _ = audit(self.source, self.checkpoint)
        self.assertEqual(report['numeric_proposals'], 0)
        self.assertEqual(report['abstentions'], 6)

    def test_company_mismatch_rejected(self):
        self.pred['company_id'] = 999
        self.make_checkpoint()
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_kind_mismatch_rejected(self):
        self.pred['prediction']['detected_kind'] = 'interview'
        self.make_checkpoint()
        with self.assertRaises(CheckpointError):
            load_handoff(self.source, self.checkpoint)

    def test_stored_run_edited_or_incomplete_rejected(self):
        normalized = {'dimensions': {
            k: {'score': v['score'], 'confidence': v['confidence'],
                'evidence': [v['evidence']] if v['score'] is not None else [],
                'explanation': v['explanation']}
            for k, v in self.pred['prediction']['dimensions'].items()}}
        rows = [SimpleNamespace(key=k, semantic_status='unreviewed', **v)
                for k, v in normalized['dimensions'].items()]
        self.assertTrue(stored_scores_match(normalized, rows))
        rows[0].score = 10
        self.assertFalse(stored_scores_match(normalized, rows))
        rows[0].score = 2
        self.assertFalse(stored_scores_match(normalized, rows[:-1]))


if __name__ == '__main__':
    unittest.main()
