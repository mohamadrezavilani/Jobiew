"""Additive, immutable review/score history; v1 ratings remain untouched.

Phase one only creates the structure and classification queue. No AI/API calls,
no backfill of numeric values, and no migration of historical five-axis scores.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from .registry import AXES, VERSIONS, axes_for, version_for

KIND_CHOICES = [('work', 'شرایط کاری'), ('interview', 'شرایط مصاحبه')]
VERSION_CHOICES = [('work6_v2', 'شش معیار شرایط کاری'), ('interview6_v2', 'شش معیار شرایط مصاحبه')]
AXIS_CHOICES = [(a.key, a.label) for group in AXES.values() for a in group]


class CriteriaReviewEvent(models.Model):
    """Human review of a comment's CLASSIFICATION only, not of its AI scores.

    Absence of a current confirmed event means re-review is still required.
    Even a previous confirmation becomes stale after source content changes.
    """
    DECISIONS = [
        ('confirmed', 'دسته‌بندی تأیید شد؛ آمادهٔ مرحلهٔ ارزیابی'),
        ('needs_revision', 'دسته‌بندی نیازمند اصلاح است'),
        ('excluded', 'این روایت نباید برای معیارها استفاده شود'),
    ]
    experience = models.ForeignKey('experiences.PublicExperience', on_delete=models.PROTECT, related_name='dual_criteria_review_events')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source_kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    criteria_version = models.CharField(max_length=16, choices=VERSION_CHOICES)
    source_content_sha256 = models.CharField(max_length=64)
    decision = models.CharField(max_length=20, choices=DECISIONS)
    suggested_kind = models.CharField(max_length=20, choices=KIND_CHOICES, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        indexes = [models.Index(fields=['experience', '-created_at'], name='wi_dual_review_exp_ts')]

    def clean(self):
        super().clean()
        if not self.experience_id:
            raise ValidationError('Source experience is required')
        exp = self.experience
        if exp.source_kind not in VERSIONS or self.source_kind != exp.source_kind:
            raise ValidationError('Stored source_kind does not match the experience')
        if self.criteria_version != version_for(exp.source_kind):
            raise ValidationError('Criteria version does not match experience type')
        if len(exp.content_sha256 or '') != 64 or self.source_content_sha256 != exp.content_sha256:
            raise ValidationError('Review refers to stale source content')
        if self.decision != 'confirmed' and len(self.note.strip()) < 8:
            raise ValidationError('Explain why the comment needs revision/exclusion')
        if self.decision == 'confirmed' and self.suggested_kind:
            raise ValidationError('A confirmed type cannot have a different proposed type')
        if self.suggested_kind and self.suggested_kind == exp.source_kind:
            raise ValidationError('Suggested new kind must differ from existing kind')

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('Review history is append-only')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Review history is append-only')


class CriteriaAnalysis(models.Model):
    """Future new-version scoring runs, isolated from legacy AiAssessment rows.

    No existing data is migrated or recalculated when this table is created.
    Publication of these results is NOT implemented in the architecture phase.
    """
    experience = models.ForeignKey('experiences.PublicExperience', on_delete=models.PROTECT, related_name='dual_criteria_analyses')
    criteria_version = models.CharField(max_length=16, choices=VERSION_CHOICES)
    source_content_sha256 = models.CharField(max_length=64)
    model_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=120)
    run_id = models.CharField(max_length=120, unique=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    review_status = models.CharField(max_length=24, default='unreviewed')
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if not self.experience_id:
            return
        if self.criteria_version != version_for(self.experience.source_kind):
            raise ValidationError('Cross-kind or outdated criteria version')
        if self.source_content_sha256 != self.experience.content_sha256:
            raise ValidationError('Assessment must match current source hash')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CriteriaAxisScore(models.Model):
    """Six-axis results reserved for the next phase: NULL is no score, not zero."""
    analysis = models.ForeignKey(CriteriaAnalysis, on_delete=models.PROTECT, related_name='axis_scores')
    key = models.CharField(max_length=60, choices=AXIS_CHOICES)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    evidence = models.JSONField(default=list, blank=True)
    explanation = models.TextField(blank=True)
    semantic_status = models.CharField(max_length=24, default='unreviewed')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['analysis', 'key'], name='wi_dual_score_one_key_per_run'),
            models.CheckConstraint(condition=Q(score__isnull=True) | (Q(score__gte=1) & Q(score__lte=10)), name='wi_dual_score_range_1_10'),
            models.CheckConstraint(condition=Q(confidence__gte=0) & Q(confidence__lte=100), name='wi_dual_confidence_range_100'),
        ]

    def clean(self):
        super().clean()
        if not self.analysis_id:
            return
        valid_keys = {a.key for a in axes_for(self.analysis.experience.source_kind)}
        if self.key not in valid_keys:
            raise ValidationError('Cannot attach an interview axis to a work analysis, or vice versa')
        if self.score is None and self.confidence:
            raise ValidationError('Abstention requires zero confidence')
        if self.score is not None and not self.evidence:
            raise ValidationError('A numerical score requires source evidence')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

class CriteriaScoreReviewEvent(models.Model):
    """Append-only human score review; neither edits the source nor publishes ratings."""
    analysis = models.ForeignKey(CriteriaAnalysis, on_delete=models.PROTECT,
                                 related_name='human_score_review_events')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source_content_sha256 = models.CharField(max_length=64)
    decisions = models.JSONField(default=dict)
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        constraints = [models.UniqueConstraint(fields=['analysis'], name='wi_dual_one_human_review')]

    def clean(self):
        super().clean()
        if not self.analysis_id:
            raise ValidationError('Analysis is required')
        if self.source_content_sha256 != self.analysis.source_content_sha256:
            raise ValidationError('Review has a stale source content hash')
        if not isinstance(self.decisions, dict) or set(self.decisions) != {
                a.key for a in axes_for(self.analysis.experience.source_kind)}:
            raise ValidationError('All six independent axes require a decision')
        if any(x not in {'approve', 'reject', 'abstain'} for x in self.decisions.values()):
            raise ValidationError('Invalid score review decision')
        if not 12 <= len((self.note or '').strip()) <= 1500:
            raise ValidationError('Human review note must be 12..1500 characters')

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('Score review events are append-only')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Score review events are append-only')
