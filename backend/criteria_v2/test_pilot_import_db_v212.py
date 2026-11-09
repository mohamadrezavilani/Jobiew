"""Isolated Django database acceptance. No real private files or paid AI calls."""
from django.test import TestCase
from companies.models import Company
from experiences.models import PublicExperience
from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore, CriteriaScoreReviewEvent
from criteria_v2.test_pilot_import_v212 import fixture
from criteria_v2.pilot_import_v212 import load_private_bundle, PilotImportError, ENGINE
from criteria_v2.management.commands.import_dual6_pilot_v212 import _stage_cases


class PrivatePilotStagingDBTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company=Company.objects.create(
            id='pilot-v212-test',source_url='https://example.test/v212',
            source_name='نمونه',display_name='شرکت آزمایشی')
        s,_,_=fixture()
        cls.story=s['cases'][0]['story']
        cls.exp=PublicExperience.objects.create(
            pk=101,company=cls.company,source_url='https://example.test/v212/story',
            source_kind='work',title='test',body='',content_sha256='a'*64,
            copyright_review='pending',company_attribution_status='unverified')

    def _cases(self):
        return load_private_bundle(*fixture())

    def test_dry_run_never_writes(self):
        from unittest.mock import patch
        with patch('criteria_v2.management.commands.import_dual6_pilot_v212.story_from_experience',return_value=self.story):
            result=_stage_cases(self._cases())
        self.assertEqual(result['would_insert'],1)
        self.assertEqual(CriteriaAnalysis.objects.count(),0)

    def test_apply_only_private_proposals_then_idempotent(self):
        from unittest.mock import patch
        with patch('criteria_v2.management.commands.import_dual6_pilot_v212.story_from_experience',return_value=self.story):
            result=_stage_cases(self._cases(),apply=True)
            again=_stage_cases(self._cases(),apply=True)
        self.assertEqual(result['inserted'],1)
        self.assertEqual(again['inserted'],0)
        self.assertEqual(CriteriaAnalysis.objects.count(),1)
        self.assertEqual(CriteriaAxisScore.objects.count(),6)
        row=CriteriaAnalysis.objects.get()
        self.assertEqual(row.review_status,'pilot_unverified')
        self.assertEqual(row.raw_payload['engine'],ENGINE)
        self.assertNotIn(self.story,str(row.raw_payload))
        self.assertEqual(CriteriaScoreReviewEvent.objects.count(),0)
        self.assertFalse(CriteriaAxisScore.objects.filter(semantic_status='approved').exists())

    def test_source_change_aborts_without_writes(self):
        with self.assertRaises(PilotImportError): _stage_cases(self._cases(),apply=True)
        self.assertFalse(CriteriaAnalysis.objects.exists())

    def test_blocked_rights_prevent_import(self):
        from unittest.mock import patch
        PublicExperience.objects.filter(pk=self.exp.pk).update(copyright_review='blocked')
        with patch('criteria_v2.management.commands.import_dual6_pilot_v212.story_from_experience',return_value=self.story):
            with self.assertRaises(PilotImportError):_stage_cases(self._cases(),apply=True)
        self.assertFalse(CriteriaAnalysis.objects.exists())
