"""Append-only, research-only provenance for revised AI scoring suggestions.

This is not a human sign-off and never affects public RatingSnapshot.
"""
import re
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class SemanticScoreOverride(models.Model):
    """One revision of a single existing AiDimension; original score is immutable.

    PROPOSED rows do not affect any reports. ACTIVE_PROVISIONAL rows may replace
    the effective score ONLY in staff research aggregates. Later revisions can
    supersede older ones without deleting historical entries.
    """
    STATUSES = [('proposed', 'پیشنهاد AI، غیرفعال'),
                ('active_provisional', 'فعال صرفاً در محاسبات داخلی')]
    ACTIONS = [('revise', 'اصلاح نمره'), ('abstain', 'حذف نمره فاقد شاهد')]

    dimension = models.ForeignKey('assessments.AiDimension', on_delete=models.PROTECT,
                                  related_name='semantic_overrides')
    batch_id = models.CharField(max_length=120)
    action = models.CharField(max_length=12, choices=ACTIONS)
    baseline_score = models.PositiveSmallIntegerField(null=True, blank=True)
    proposed_score = models.PositiveSmallIntegerField(null=True, blank=True)
    source_content_sha256 = models.CharField(max_length=64)
    source_row_sha256 = models.CharField(max_length=64)
    evidence_excerpt = models.TextField(blank=True)
    rationale = models.TextField()
    review_method = models.CharField(max_length=100, default='offline_AI_recommendation')
    status = models.CharField(max_length=20, choices=STATUSES, default='proposed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['dimension', 'batch_id'], name='wi_sem_override_dim_batch'),
            models.CheckConstraint(condition=Q(baseline_score__isnull=True) | (Q(baseline_score__gte=1) & Q(baseline_score__lte=10)), name='wi_sem_override_base_1_10'),
            models.CheckConstraint(condition=Q(proposed_score__isnull=True) | (Q(proposed_score__gte=1) & Q(proposed_score__lte=10)), name='wi_sem_override_new_1_10'),
        ]
        indexes = [models.Index(fields=['dimension', '-id'], name='wi_sem_override_dim_pk')]

    def clean(self):
        errors = {}
        if self.pk is not None:
            errors['batch_id'] = 'Revision entries are append-only.'
        if self.action == 'revise' and (type(self.proposed_score) is not int or not 1 <= self.proposed_score <= 10):
            errors['proposed_score'] = 'Revisions need a score between 1 and 10.'
        if self.action == 'abstain' and self.proposed_score is not None:
            errors['proposed_score'] = 'Abstentions require a NULL score.'
        if not self.batch_id or len(self.batch_id) > 120:
            errors['batch_id'] = 'Batch id required (up to 120 chars).'
        for f in ('source_content_sha256', 'source_row_sha256'):
            if not re.fullmatch(r'[0-9a-fA-F]{64}', str(getattr(self, f, ''))):
                errors[f] = 'Expected a SHA-256 hex digest.'
        if len(self.rationale.strip()) < 12:
            errors['rationale'] = 'A meaningful explanation is required.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('Semantic revisions are append-only')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Semantic revisions are append-only')
