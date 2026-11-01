"""Votes are separate from AI evidence. Public voting is disabled until real identity integration."""
from django.conf import settings
from django.db import models

class IdentityVerification(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workplace_identity')
    status = models.CharField(max_length=20, choices=[('pending','در انتظار'),('verified','تأیید شده'),('rejected','رد شده')],default='pending')
    provider = models.CharField(max_length=40, blank=True)  # No national IDs, phone numbers or raw Shahkar responses
    checked_at = models.DateTimeField(null=True, blank=True)

class VoteRevision(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workplace_vote_history')
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT)
    scores = models.JSONField()
    issued_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=100, unique=True)

    class Meta:
        indexes = [models.Index(fields=['company','issued_at'])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('VoteRevision is append-only')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('VoteRevision is append-only')

class ActiveVote(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,primary_key=True)
    revision = models.OneToOneField(VoteRevision,on_delete=models.PROTECT)
