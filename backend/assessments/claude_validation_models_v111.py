"""Optional, paid, read-only Claude second-opinion records.

No relationship to AI publication or the human approval workflow. An independent
verifier never changes AiAssessment/AiDimension scores or approval flags.
"""
from django.conf import settings
from django.db import models


class ClaudeValidationRun(models.Model):
    assessment = models.ForeignKey('assessments.AiAssessment', on_delete=models.PROTECT,
                                   related_name='claude_validation_runs')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name='jobiew_claude_validations')
    status = models.CharField(max_length=16, choices=[('running','درحال بررسی'),
                              ('completed','تکمیل‌شده'),('failed','ناموفق')], default='running')
    model_id = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=32, default='independent_five_v111')
    source_sha256 = models.CharField(max_length=64)
    original_scores = models.JSONField(default=dict)
    claude_results = models.JSONField(default=dict)
    comparison = models.JSONField(default=dict)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=9, decimal_places=6, default=0)
    error_type = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [models.Index(fields=['assessment', '-id'], name='wi_claude_assessment_idx')]

    def __str__(self):
        return f'Claude #{self.pk}: assessment {self.assessment_id} ({self.status})'
