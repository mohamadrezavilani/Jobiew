"""Inert synthetic cumulative-checkpoint regression. No source texts, AI, or DB."""
from hashlib import sha256
import copy
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from .checkpoint_cumulative_v221 import validate_cumulative, CheckpointError, AXES

SOURCE_SHA = 'b' * 64

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8')


def synthetic(*, quality_scope='structural_schema_and_verbatim_evidence_only'):
    story = 'یک روایت ساختگی صرفاً برای تست اعتبارسنجی فرمت و نقل قول.'
    digest = sha256(story.encode('utf8')).hexdigest()
    ledger = [
        {'experience_id': 1, 'kind': 'work', 'company_id': 'synthetic-company',
         'source_content_sha256': 'a' * 64, 'story_sha256': digest,
         'story_length': len(story), 'status': 'assistant_reviewed_draft',
         'exact_duplicate_of_experience_id': None, 'issue': None,
         'review_required_before_publication': True},
        {'experience_id': 2, 'kind': 'interview', 'company_id': 'synthetic-other',
         'source_content_sha256': 'c' * 64, 'story_sha256': 'd' * 64,
         'story_length': 70, 'status': 'awaiting_assistant_review',
         'exact_duplicate_of_experience_id': None, 'issue': None,
         'review_required_before_publication': True},
    ]
    evidence = 'روایت ساختگی صرفاً برای تست اعتبارسنجی'
    dims = {}
    for i, axis in enumerate(AXES['work']):
        dims[axis] = {'score': 7 if i == 0 else None,
                      'confidence': 80 if i == 0 else 0,
                      'evidence': evidence if i == 0 else '',
                      'explanation': 'شاهد مصنوعی فقط برای آزمایش قرارداد داده‌ها.'}
    prediction = {'experience_id': 1, 'company_id': 'synthetic-company',
                  'kind': 'work', 'source_content_sha256': 'a' * 64,
                  'story_sha256': digest, 'state': 'assistant_reviewed_draft',
                  'review_status': 'unverified_private_proposal',
                  'model_name': 'synthetic-test',
                  'prediction': {'detected_kind': 'work', 'kind_confidence': 85,
                                 'dimensions': dims}}
    checkpoint = {
        'source_archive_sha256': SOURCE_SHA,
        'source_records_verified': 2, 'source_kind_counts': {'work': 1, 'interview': 1},
        'source_rights': 'NOT_ESTABLISHED', 'company_attribution': 'UNVERIFIED',
        'publication': 'DISABLED', 'independent_semantic_accuracy_established': False,
        'no_independent_human_gold': True, 'assistant_reviewed_records': 1,
        'assistant_numeric_axis_proposals': 1, 'assistant_null_axis_proposals': 5,
        'status_counts': {'assistant_reviewed_draft': 1, 'awaiting_assistant_review': 1},
        'exact_duplicate_stories': 0,
    }
    quality = {
        'validation': 'PASS', 'validation_scope': quality_scope,
        'semantic_claims_fact_checked': False, 'publication_enabled': False,
        'reviewed_record_count': 1, 'numeric_axis_count': 1, 'abstained_axis_count': 5,
        'by_kind': {'work': {'reviewed': 1}, 'interview': {'reviewed': 0}},
    }
    return {'checkpoint.json': encode(checkpoint), 'quality_audit.json': encode(quality),
            'ledger.jsonl': b'\n'.join(encode(x) for x in ledger),
            'assistant_predictions.jsonl': encode(prediction),
            'manual_notes_untrusted.py': b'raise RuntimeError("SHOULD_NOT_RUN")'}


def archive(path, payload, *, manifest_override=None):
    manifest = {n: sha256(content).hexdigest() for n, content in payload.items()}
    if manifest_override:
        manifest.update(manifest_override)
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as z:
        for n, content in payload.items():
            z.writestr(n, content)
        z.writestr('files_sha256.json', encode(manifest))
    return sha256(path.read_bytes()).hexdigest()


class CumulativeCheckpointPureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'checkpoint.zip'
        self.payload = synthetic()

    def tearDown(self):
        self.tmp.cleanup()

    def run_loader(self, payload=None, *, manifest_override=None, checkpoint_sha=None,
                   source_sha=SOURCE_SHA):
        actual = archive(self.path, payload or self.payload,
                         manifest_override=manifest_override)
        return validate_cumulative(self.path,
                                   expected_checkpoint_sha256=checkpoint_sha or actual,
                                   expected_source_sha256=source_sha)

    def test_accept_synthetic_without_executing_archive_python(self):
        rows, ledger, summary = self.run_loader()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(ledger), 2)
        self.assertEqual(summary['numeric_proposals'], 1)
        self.assertEqual(summary['abstentions'], 5)
        self.assertEqual(summary['publication'], 'DISABLED')
        self.assertFalse(summary['source_archive_verified_here'])

    def test_accepts_v65_scope_and_779_member_archive(self):
        other = synthetic(
            quality_scope='custom_independent_structural_schema_and_verbatim_evidence')
        # The final v65 handoff contains 779 members; archive scripts stay inert.
        for i in range(773):
            other[f'history/manual_notes_{i:04d}.py'] = b'# inert, hashed checkpoint history\\n'
        rows, ledger, summary = self.run_loader(other)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(ledger), 2)
        self.assertEqual(summary['unexecuted_archive_members_checked'], 778)

    def test_rejects_unknown_quality_audit_scope(self):
        other = synthetic(quality_scope='semantic_truth_and_rights_verified')
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_requires_both_independently_pinned_sha256(self):
        with self.assertRaises(CheckpointError):
            self.run_loader(checkpoint_sha='0'*64)
        with self.assertRaises(CheckpointError):
            self.run_loader(source_sha='1'*64)

    def test_rejects_member_hash_tampering_even_when_zip_sha_is_pinned(self):
        with self.assertRaises(CheckpointError):
            self.run_loader(manifest_override={'checkpoint.json':'0'*64})

    def test_rejects_duplicate_or_missing_ledger_source_id(self):
        other=copy.deepcopy(self.payload)
        lines=other['ledger.jsonl'].splitlines()
        row=json.loads(lines[1]);row['experience_id']=1
        other['ledger.jsonl']=lines[0]+b'\n'+encode(row)
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_rejects_unauthorized_publication_flag(self):
        other=copy.deepcopy(self.payload)
        cp=json.loads(other['checkpoint.json']);cp['publication']='ENABLED'
        other['checkpoint.json']=encode(cp)
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_rejects_numeric_score_tamper_despite_updated_manifest(self):
        other=copy.deepcopy(self.payload)
        row=json.loads(other['assistant_predictions.jsonl'])
        first=AXES['work'][0]
        row['prediction']['dimensions'][first]['score']=0
        other['assistant_predictions.jsonl']=encode(row)
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_rejects_all_null_when_marked_as_numeric(self):
        other=copy.deepcopy(self.payload)
        p=json.loads(other['assistant_predictions.jsonl'])
        p['prediction']['dimensions'][AXES['work'][0]]={
            'score':None, 'confidence':0,'evidence':'',
            'explanation':'هیچ شاهد کافی برای این محور وجود ندارد.'}
        other['assistant_predictions.jsonl']=encode(p)
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_rejects_duplicate_json_object_keys(self):
        other=copy.deepcopy(self.payload)
        other['checkpoint.json']=other['checkpoint.json'].replace(b'"publication":',b'"publication":"DISABLED", "publication":')
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_rejects_invalid_source_duplicate_claim(self):
        other=copy.deepcopy(self.payload)
        lines=other['ledger.jsonl'].splitlines()
        row=json.loads(lines[1]);row['exact_duplicate_of_experience_id']=1
        other['ledger.jsonl']=lines[0]+b'\n'+encode(row)
        cp=json.loads(other['checkpoint.json']);cp['exact_duplicate_stories']=1
        other['checkpoint.json']=encode(cp)
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

    def test_rejects_new_members_without_manifest_hash(self):
        other=copy.deepcopy(self.payload)
        other['unexpected.txt']=b'not approved'
        # Overriding the unexpected member digest with an invalid digest rejects.
        with self.assertRaises(CheckpointError):
            self.run_loader(other, manifest_override={'unexpected.txt':'0'*64})

    def test_rejects_wrong_kind_axes(self):
        other=copy.deepcopy(self.payload)
        row=json.loads(other['assistant_predictions.jsonl'])
        row['prediction']['dimensions']['wrong_axis']=row['prediction']['dimensions'].pop(AXES['work'][0])
        other['assistant_predictions.jsonl']=encode(row)
        with self.assertRaises(CheckpointError):
            self.run_loader(other)

if __name__=='__main__':
    unittest.main()