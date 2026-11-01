"""Private service only: authentication and external identity confirmation needed for real use."""
import calendar
from datetime import datetime
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from assessments.models import DIMENSIONS
from companies.models import Company
from .models import ActiveVote, IdentityVerification, VoteRevision

class VoteDenied(ValueError):
    pass


def after_three_calendar_months(value):
    y = value.year + (value.month+2)//12
    m = (value.month+2)%12 + 1
    d = min(value.day,calendar.monthrange(y,m)[1])
    return value.replace(year=y,month=m,day=d)


def validate_scores(scores):
    known={x[0] for x in DIMENSIONS}
    if not isinstance(scores,dict) or not scores or set(scores)-known:
        raise VoteDenied('Invalid voting dimensions')
    if any(type(v) is not int or v < 1 or v > 10 for v in scores.values()):
        raise VoteDenied('Every score must be an integer 1..10')
    return scores


@transaction.atomic
def cast_vote(*, user, company_id, scores, idempotency_key):
    if not getattr(user,'is_authenticated',False) or user.pk is None:
        raise VoteDenied('Authenticated user required')
    if not isinstance(idempotency_key,str) or not 10 <= len(idempotency_key) <= 100:
        raise VoteDenied('Invalid idempotency key')
    scores=validate_scores(scores)
    user=get_user_model()._default_manager.select_for_update().get(pk=user.pk)
    replay=VoteRevision.objects.filter(idempotency_key=idempotency_key).first()
    if replay:
        if replay.user_id != user.pk or replay.company_id != company_id or replay.scores != scores:
            raise VoteDenied('Idempotency conflict')
        return replay, True
    if not IdentityVerification.objects.filter(user=user,status='verified').exists():
        raise VoteDenied('External identity verification required')
    company=Company.objects.get(pk=company_id)
    if not company.vote_enabled:
        raise VoteDenied('Voting is not enabled for this company')
    active=ActiveVote.objects.select_for_update().select_related('revision').filter(user=user).first()
    now=timezone.now()
    if active and now < after_three_calendar_months(active.revision.issued_at):
        raise VoteDenied('Voting change locked for three calendar months')
    revision=VoteRevision.objects.create(user=user,company=company,scores=scores,issued_at=now,idempotency_key=idempotency_key)
    ActiveVote.objects.update_or_create(user=user,defaults={'revision':revision})
    return revision,False
