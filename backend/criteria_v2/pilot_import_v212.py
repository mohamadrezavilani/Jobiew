"""Strict, pure validation of privately labelled Jobiew v211 pilot suggestions.

Only source-aligned AI *proposals*, NOT gold labels, approval, or publication.
No database, network, or filesystem writes.  Never print source text.
"""
import hashlib
import json
from pathlib import Path

from .engine_v207 import story_digest, validate_response, ProposalError
from .registry import axes_for

PILOT_VERSION = 'jobiew_dual6_pilot_v211'
ENGINE = 'jobiew_private_assistant_pilot_v212'


class PilotImportError(ValueError):
    pass


def _index(document, required_keys, name):
    if not isinstance(document, dict) or set(document) != {'pilot_version', 'cases'}:
        raise PilotImportError(f'{name}: invalid document layout')
    if document['pilot_version'] != PILOT_VERSION or not isinstance(document['cases'], list):
        raise PilotImportError(f'{name}: invalid pilot version or cases')
    indexed = {}
    for case in document['cases']:
        if not isinstance(case, dict) or set(case) != required_keys:
            raise PilotImportError(f'{name}: invalid case fields')
        cid = case.get('case_id')
        if not isinstance(cid, str) or not 1 <= len(cid) <= 120 or cid in indexed:
            raise PilotImportError(f'{name}: missing or duplicate case ID')
        indexed[cid] = case
    return indexed


def load_private_bundle(stories_doc, mapping_doc, prediction_doc):
    """Returns strict case records; stories stay in memory and are never logged."""
    stories = _index(stories_doc, {'case_id', 'kind', 'story'}, 'stories')
    mapping = _index(mapping_doc,
                     {'case_id', 'source_experience_id', 'length_group'}, 'mapping')
    predictions = _index(prediction_doc, {'case_id', 'prediction'}, 'predictions')
    if not stories or set(stories) != set(mapping) or set(stories) != set(predictions):
        raise PilotImportError('Private files must contain the same nonempty case ID set')
    if len(stories) > 100:
        raise PilotImportError('Pilot too large; maximum 100 private cases')
    source_ids = set()
    result = []
    for cid, source in stories.items():
        kind = source['kind']
        story = source['story']
        if kind not in ('work', 'interview') or not isinstance(story, str) or not 50 <= len(story.strip()) <= 8000:
            raise PilotImportError('Unsupported kind or source story length')
        mapping_row = mapping[cid]
        exp_id = mapping_row['source_experience_id']
        if type(exp_id) is not int or exp_id <= 0 or exp_id in source_ids:
            raise PilotImportError('Invalid or repeated source experience ID')
        source_ids.add(exp_id)
        if mapping_row['length_group'] not in ('short','medium','long'):
            raise PilotImportError('Invalid source length group')
        pred = predictions[cid]['prediction']
        if not isinstance(pred, dict):
            raise PilotImportError('Incomplete AI proposals; never fill in blanks automatically')
        try:
            # Reuse the same six-axis/evidence validation as the deployed v207 engine.
            response = {'stop_reason':'end_turn', 'content':[
                {'type':'text','text':json.dumps(pred, ensure_ascii=False)}]}
            clean = validate_response(response, kind=kind, story=story)
            if clean['status'] != 'unreviewed' or clean['dimensions'] is None:
                raise PilotImportError('AI disagrees with recorded experience kind')
            if len(clean['dimensions']) != len(axes_for(kind)):
                raise PilotImportError('Missing dimension proposals')
        except (ProposalError, TypeError, ValueError) as exc:
            if isinstance(exc, PilotImportError):
                raise
            raise PilotImportError('Invalid AI prediction schema or evidence: ' + str(exc)) from None
        normalized = json.dumps(pred, ensure_ascii=False, sort_keys=True, separators=(',',':'))
        proposal_sha = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        result.append({
            'case_id':cid, 'experience_id':exp_id, 'kind':kind,
            'story':story, 'story_sha256':story_digest(story),
            'prediction_sha256':proposal_sha, 'dimensions':clean['dimensions'],
            'detected_kind':clean['detected_kind'],
            'kind_confidence':clean['kind_confidence'],
        })
    return result


def load_from_files(stories_path, mapping_path, predictions_path):
    try:
        documents = [json.loads(Path(x).read_text(encoding='utf-8-sig'))
                     for x in (stories_path, mapping_path, predictions_path)]
    except (OSError, ValueError, TypeError) as exc:
        raise PilotImportError('Cannot read valid private JSON documents') from None
    return load_private_bundle(*documents)


def deterministic_run_id(case, source_sha256):
    material = '|'.join((ENGINE, str(case['experience_id']), source_sha256,
                         case['story_sha256'],case['prediction_sha256']))
    return 'pilotv212_' + hashlib.sha256(material.encode('utf-8')).hexdigest()


def aggregate_report(cases):
    scores = {'work':0,'interview':0}
    counted = {'work':0,'interview':0}
    for case in cases:
        counted[case['kind']] += 1
        scores[case['kind']] += sum(v['score'] is not None for v in case['dimensions'].values())
    total = sum(counted.values())
    return {'cases':total, 'work':counted['work'], 'interview':counted['interview'],
            'dimensions_checked':6*total, 'numeric_proposals':sum(scores.values()),
            'abstentions':6*total-sum(scores.values()),
            'numeric_by_kind':scores, 'source_text_in_report':False,
            'review_status':'pilot_unverified','publication':'DISABLED',
            'human_reference':'NOT_INDEPENDENT','external_api_calls':0}
