"""v46 review-assist static integration test (offline; no database/API required)."""
from pathlib import Path
from django.test import SimpleTestCase


class LocationReviewAssistV46Tests(SimpleTestCase):
    @staticmethod
    def script():
        return (Path(__file__).parent/'static'/'locations'/'js'/'review_evidence_helper_v46.js').read_text(encoding='utf-8')

    def test_admin_template_loads_assistant_without_replacing_map(self):
        template=(Path(__file__).parent/'templates'/'admin'/'locations'/'companylocationreviewevent'/'change_form.html').read_text(encoding='utf-8')
        self.assertIn("'locations/js/location_picker_v39.js'",template)
        self.assertIn("'locations/js/review_evidence_helper_v46.js'",template)

    def test_provenance_is_required_before_drafting_confirmation(self):
        js=self.script()
        self.assertIn('if (!checkUrl(evidence))',js)
        self.assertIn('if (!confirmed)',js)
        self.assertIn("decision !== 'verified'",js)
        self.assertIn("checked.addEventListener('change'",js)

    def test_user_evidence_remains_manual_and_changes_invalidate_draft(self):
        js=self.script()
        self.assertNotIn('e.value=',js)
        self.assertIn("e.addEventListener('input',()=>invalidate",js)
        self.assertIn("lat.addEventListener('change',()=>invalidate",js)
        self.assertIn("lon.addEventListener('change',()=>invalidate",js)
