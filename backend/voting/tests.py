from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from companies.models import Company
from .models import ActiveVote,VoteRevision,IdentityVerification
from .services import cast_vote,VoteDenied,after_three_calendar_months

class VotingTests(TestCase):
    def setUp(self):
        self.u=get_user_model().objects.create_user(username='tester',password='not-a-real-secret')
        self.c1=Company.objects.create(id='c1',source_url='https://a.example',source_name='A',display_name='A',vote_enabled=True)
        self.c2=Company.objects.create(id='c2',source_url='https://b.example',source_name='B',display_name='B',vote_enabled=True)

    def test_verified_identity_required(self):
        with self.assertRaises(VoteDenied):cast_vote(user=self.u,company_id=self.c1.pk,scores={'work_conditions_pressure':7},idempotency_key='first-event-001')

    def test_single_active_three_months_history_and_replay(self):
        IdentityVerification.objects.create(user=self.u,status='verified',provider='test-only')
        r,replayed=cast_vote(user=self.u,company_id=self.c1.pk,scores={'work_conditions_pressure':7},idempotency_key='first-event-001')
        self.assertFalse(replayed)
        r2,replayed=cast_vote(user=self.u,company_id=self.c1.pk,scores={'work_conditions_pressure':7},idempotency_key='first-event-001')
        self.assertTrue(replayed);self.assertEqual(r.pk,r2.pk)
        with self.assertRaises(VoteDenied):cast_vote(user=self.u,company_id=self.c2.pk,scores={'work_conditions_pressure':8},idempotency_key='second-event-002')
        VoteRevision.objects.filter(pk=r.pk).update(issued_at=timezone.now()-timedelta(days=120))
        r3,replayed=cast_vote(user=self.u,company_id=self.c2.pk,scores={'work_conditions_pressure':8},idempotency_key='second-event-002')
        self.assertEqual(VoteRevision.objects.count(),2)
        self.assertEqual(ActiveVote.objects.get(user=self.u).revision,r3)
        with self.assertRaises(ValueError):r3.delete()

    def test_legacy_vote_key_rejected_for_new_votes(self):
        from .services import validate_scores
        with self.assertRaises(VoteDenied):
            validate_scores({'workload': 7})

    def test_month_end(self):
        from datetime import datetime,timezone as utc
        self.assertEqual(after_three_calendar_months(datetime(2026,1,31,tzinfo=utc.utc)).date().isoformat(),'2026-04-30')
