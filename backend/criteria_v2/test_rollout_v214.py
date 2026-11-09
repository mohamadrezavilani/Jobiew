"""Pure rollout contract. Intentionally no API or database."""
import unittest
from .rollout_v214 import decide, summarize


class RolloutV214PureTests(unittest.TestCase):
    BASE=dict(kind='work', copyright_review='approved',
              company_attribution_status='verified', independence_status='unknown',
              source_digest='a'*64, story_length=120,
              classification_decision='confirmed', classification_digest='a'*64,
              existing_analysis=False)

    def get(self, **changes):
        return decide(**{**self.BASE, **changes})

    def test_ready_only_fully_cleared(self):
        self.assertEqual(self.get(), 'ready')

    def test_pending_copyright_denied(self):
        self.assertEqual(self.get(copyright_review='pending'), 'copyright_not_approved')

    def test_blocked_copyright_denied(self):
        self.assertEqual(self.get(copyright_review='blocked'), 'copyright_not_approved')

    def test_unverified_attribution_denied(self):
        self.assertEqual(self.get(company_attribution_status='unverified'), 'attribution_not_verified')

    def test_known_duplicate_denied(self):
        self.assertEqual(self.get(independence_status='duplicate'), 'known_duplicate')

    def test_missing_digest_denied(self):
        self.assertEqual(self.get(source_digest='x'*64), 'source_digest_invalid')

    def test_short_story_denied(self):
        self.assertEqual(self.get(story_length=49), 'text_out_of_range')

    def test_long_story_denied(self):
        self.assertEqual(self.get(story_length=8001), 'text_out_of_range')

    def test_missing_classification_denied(self):
        self.assertEqual(self.get(classification_decision=None), 'classification_not_confirmed')

    def test_stale_classification_denied(self):
        self.assertEqual(self.get(classification_digest='b'*64), 'classification_not_confirmed')

    def test_excluded_classification_denied(self):
        self.assertEqual(self.get(classification_decision='excluded'), 'classification_not_confirmed')

    def test_prior_pilot_denied(self):
        self.assertEqual(self.get(existing_analysis=True), 'already_evaluated')

    def test_wrong_kind_denied(self):
        self.assertEqual(self.get(kind='unknown'), 'source_kind_invalid')

    def test_summary_bounded(self):
        result = summarize([(1,'work','ready'),(2,'interview','ready'),
                            (3,'work','ready')],cap=2)
        self.assertEqual(len(result['next_batch']),2)
        self.assertEqual(result['ready_total'],3)
        self.assertEqual(result['changes'],0)

    def test_summary_no_raw_source(self):
        result = summarize([(1,'work','copyright_not_approved')])
        self.assertNotIn('story',str(result).lower())

    def test_invalid_cap(self):
        with self.assertRaises(ValueError):summarize([],cap=0)

    def test_duplicate_ids(self):
        with self.assertRaises(ValueError): summarize([(2,'work','ready'),(2,'work','ready')])

    def test_invalid_cursor(self):
        with self.assertRaises(ValueError): summarize([],after_id=-1)

if __name__=='__main__': unittest.main()
