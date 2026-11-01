"""Preserve source provenance; source scores are NEVER target AI dimension scores."""
from django.conf import settings
from django.db import models


class PublicExperience(models.Model):
    KIND = [('work','تجربه کاری'), ('interview','تجربه مصاحبه')]
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='experiences')
    source_url = models.URLField(max_length=1500, unique=True)
    source_site = models.CharField(max_length=100, default='tajrobewiki.com')
    source_kind = models.CharField(max_length=20, choices=KIND)
    title = models.TextField()
    job_title = models.CharField(max_length=350, blank=True)
    body = models.TextField(blank=True)  # private working copy, not displayed publicly
    pros = models.JSONField(default=list)
    cons = models.JSONField(default=list)
    published_jalali = models.CharField(max_length=100, blank=True)
    employment_period_jalali = models.CharField(max_length=200, blank=True)
    source_rating_5 = models.FloatField(null=True, blank=True)
    source_dimension_ratings = models.JSONField(default=dict)
    content_sha256 = models.CharField(max_length=64)
    crawled_at_utc = models.DateTimeField(null=True, blank=True)
    copyright_review = models.CharField(max_length=24, default='pending')
    company_attribution_status = models.CharField(max_length=24, default='unverified')
    independence_status = models.CharField(max_length=24, default='unknown')
    published_publicly = models.BooleanField(default=False)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['company','source_kind']), models.Index(fields=['content_sha256'])]

    def __str__(self):
        return f'{self.company_id}: {self.title[:70]}'


class ExperienceReviewEvent(models.Model):
    """Append-only staff decisions; NEVER automatically set published_publicly."""
    REVIEW_FIELDS = [
        ('copyright', 'مجوز استفاده و انتشار'),
        ('attribution', 'انتساب به شرکت'),
        ('independence', 'استقلال و تکراری‌بودن تجربه'),
    ]
    DECISIONS = [
        ('pending', 'در انتظار'),
        ('approved', 'مجاز (صرفاً برای این مرحله بررسی)'),
        ('blocked', 'غیرمجاز'),
        ('unverified', 'نیازمند تأیید'),
        ('verified', 'تأیید شده'),
        ('rejected', 'رد شده'),
        ('unknown', 'نامشخص'),
        ('duplicate', 'تکراری'),
    ]
    ALLOWED = {
        'copyright': {'pending', 'approved', 'blocked'},
        'attribution': {'unverified', 'verified', 'rejected'},
        'independence': {'unknown', 'verified', 'duplicate'},
    }
    experience = models.ForeignKey(PublicExperience, on_delete=models.PROTECT, related_name='review_events')
    review_field = models.CharField(max_length=16, choices=REVIEW_FIELDS)
    decision = models.CharField(max_length=24, choices=DECISIONS)
    evidence_url = models.URLField(max_length=1500, blank=True)
    rationale = models.TextField()
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='experience_review_events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if self.pk:
            errors['review_field'] = 'Experience review events are append-only.'
        if self.decision not in self.ALLOWED.get(self.review_field, set()):
            errors['decision'] = 'Decision is not valid for the selected review field.'
        if self.decision in {'approved', 'verified'} and not self.evidence_url.strip():
            errors['evidence_url'] = 'Positive review requires a source URL.'
        if len(self.rationale.strip()) < 10:
            errors['rationale'] = 'Add an explanatory note (at least 10 characters).'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from django.db import transaction
        if self.pk is not None:
            raise ValueError('Experience review events are append-only')
        self.full_clean()
        column = {'copyright': 'copyright_review', 'attribution': 'company_attribution_status',
                  'independence': 'independence_status'}[self.review_field]
        with transaction.atomic():
            super().save(*args, **kwargs)
            PublicExperience.objects.filter(pk=self.experience_id).update(**{column: self.decision})

    def delete(self, *args, **kwargs):
        raise ValueError('Experience review events are append-only')

    def __str__(self):
        return f'{self.experience_id}: {self.review_field} → {self.decision}'
