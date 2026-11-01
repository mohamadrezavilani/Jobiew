"""Unverified locations are never returned by the public map endpoint."""
from django.db import models
from django.db.models import Q


class CompanyLocation(models.Model):
    company = models.OneToOneField('companies.Company', on_delete=models.PROTECT, related_name='location')
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    evidence_url = models.URLField(max_length=1500, blank=True)
    verification_status = models.CharField(max_length=20, choices=[('unverified','نیازمند تأیید'), ('verified','تأییدشده'), ('rejected','ردشده')], default='unverified')
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(latitude__isnull=True) | (Q(latitude__gte=-90) & Q(latitude__lte=90))), name='wi_lat_range'),
            models.CheckConstraint(condition=(Q(longitude__isnull=True) | (Q(longitude__gte=-180) & Q(longitude__lte=180))), name='wi_lon_range'),
        ]

    def __str__(self):
        return f'{self.company_id}: {self.verification_status}'


class CompanyLocationReviewEvent(models.Model):
    """Editor-reviewed geography: a source-backed decision with a permanent audit trail.

    Not an assertion about office ownership or employment. The public map additionally
    requires independent company identity and Tehran checks.
    """
    from django.conf import settings as _settings

    DECISIONS = [('verified', 'مکان تأیید شد'), ('rejected', 'مکان رد شد'),
                 ('unverified', 'تأیید مکان لغو شد')]
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT,
                                related_name='location_review_events')
    decision = models.CharField(max_length=20, choices=DECISIONS)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    evidence_url = models.URLField(max_length=1500, blank=True)
    rationale = models.TextField()
    reviewer = models.ForeignKey(_settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name='location_review_events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def clean(self):
        from django.core.exceptions import ValidationError
        from decimal import Decimal, InvalidOperation
        errors = {}
        if self.pk is not None:
            errors['decision'] = 'Review history is append-only.'
        if len((self.rationale or '').strip()) < 15:
            errors['rationale'] = 'Explain the review in at least 15 characters.'
        if self.decision == 'verified':
            if len((self.address or '').strip()) < 8:
                errors['address'] = 'A source-backed street address is required.'
            if not (self.evidence_url or '').strip().startswith('https://'):
                errors['evidence_url'] = 'Approval requires an HTTPS evidence URL.'
            for name, bound in [('latitude', 90), ('longitude', 180)]:
                val = getattr(self, name)
                try:
                    if val is None or not Decimal(str(val)).is_finite() or abs(Decimal(str(val))) > bound:
                        errors[name] = 'Valid WGS84 coordinate required.'
                except (InvalidOperation, ValueError):
                    errors[name] = 'Valid WGS84 coordinate required.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from django.db import transaction
        from django.utils import timezone
        from companies.models import Company

        if self.pk is not None:
            raise ValueError('Location review history is append-only; add another decision.')
        self.full_clean()
        # Serializing decisions for one company prevents concurrent reviewers overwriting
        # each other's latest location status out of order on PostgreSQL.
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=self.company_id)
            super().save(*args, **kwargs)
            if self.decision == 'verified':
                CompanyLocation.objects.update_or_create(company_id=self.company_id, defaults={
                    'address': self.address, 'latitude': self.latitude,
                    'longitude': self.longitude, 'evidence_url': self.evidence_url,
                    'verification_status': 'verified', 'verified_at': timezone.now(),
                })
            else:
                # Preserve the previous coordinates internally for investigation;
                # revoke their public visibility immediately.
                CompanyLocation.objects.update_or_create(company_id=self.company_id, defaults={
                    'verification_status': self.decision, 'verified_at': None,
                })

    def delete(self, *args, **kwargs):
        raise ValueError('Location review history is append-only.')

    def __str__(self):
        return f'{self.company_id}: {self.decision}'
