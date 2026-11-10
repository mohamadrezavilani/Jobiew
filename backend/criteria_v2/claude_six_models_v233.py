"""Independent opt-in six-axis Claude second-opinion audit; never publishes."""
from django.conf import settings
from django.db import models


class ClaudeSixCheck(models.Model):
    """Private comparison with an existing GPT-6 checkpoint; not a score replacement."""
    analysis = models.ForeignKey(
        'criteria_v2.CriteriaAnalysis', on_delete=models.PROTECT,
        related_name='claude_six_checks')
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='claude_six_checks')
    status = models.CharField(max_length=16, choices=[
        ('running', 'در انتظار نتیجه'), ('completed', 'تکمیل‌شده'),
        ('needs_review', 'نوع تجربه نیازمند بررسی'), ('failed', 'ناموفق'),
    ], default='running')
    model_id = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=50, default='claude_six_second_opinion_v233')
    source_sha256 = models.CharField(max_length=64)
    score_sha256 = models.CharField(max_length=64)
    original_scores = models.JSONField(default=dict)
    claude_results = models.JSONField(default=dict)
    comparison = models.JSONField(default=dict)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=70, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        constraints = [models.UniqueConstraint(fields=['analysis'],
                      name='wi_one_claude_six_per_analysis')]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            previous = type(self).objects.only('status').get(pk=self.pk)
            if previous.status != 'running':
                raise ValueError('Claude six comparison is append-only after completion.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Claude six comparison audit history cannot be deleted.')
