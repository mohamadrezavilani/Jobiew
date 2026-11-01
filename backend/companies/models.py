"""Company identity is source-provisional until reviewed by an editor."""
from django.conf import settings
from django.db import models
from django.db.models import Q

VERIFICATION = [('unverified', 'نیازمند تأیید'), ('verified', 'تأییدشده'), ('rejected', 'ردشده')]


class Company(models.Model):
    id = models.CharField(max_length=24, primary_key=True, editable=False)
    source_url = models.URLField(max_length=1500, unique=True)
    source_name = models.CharField(max_length=350)
    display_name = models.CharField(max_length=350)
    industry = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    identity_status = models.CharField(max_length=20, choices=VERIFICATION, default='unverified')
    tech_status = models.CharField(max_length=20, choices=VERIFICATION, default='unverified')
    tehran_status = models.CharField(max_length=20, choices=VERIFICATION, default='unverified')
    source_work_count = models.PositiveIntegerField(default=0)
    source_interview_count = models.PositiveIntegerField(default=0)
    vote_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_name', 'id']

    def __str__(self):
        return self.display_name


class CompanyVerificationEvent(models.Model):
    """Append-only evidence trail for the three independent company checks.

    Approval here does not approve AI scores, publishing or voting.
    """
    FIELD_CHOICES = [
        ('identity', 'هویت شرکت'),
        ('tech', 'حوزه فناوری'),
        ('tehran', 'ارتباط با تهران'),
    ]
    field = models.CharField(max_length=12, choices=FIELD_CHOICES)
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='verification_events')
    decision = models.CharField(max_length=20, choices=VERIFICATION)
    evidence_url = models.URLField(max_length=1500, blank=True)
    rationale = models.TextField()
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='company_review_events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if self.pk:
            errors['field'] = 'Verification events are append-only.'
        if self.decision == 'verified' and not self.evidence_url.strip():
            errors['evidence_url'] = 'Positive verification requires a source URL.'
        if len(self.rationale.strip()) < 10:
            errors['rationale'] = 'Add an explanatory note (at least 10 characters).'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from django.db import transaction
        if self.pk is not None:
            raise ValueError('Company verification events are append-only')
        self.full_clean()
        column = {'identity': 'identity_status', 'tech': 'tech_status', 'tehran': 'tehran_status'}[self.field]
        with transaction.atomic():
            super().save(*args, **kwargs)
            Company.objects.filter(pk=self.company_id).update(**{column: self.decision})

    def delete(self, *args, **kwargs):
        raise ValueError('Company verification events are append-only')

    def __str__(self):
        return f'{self.company}: {self.field} → {self.decision}'
