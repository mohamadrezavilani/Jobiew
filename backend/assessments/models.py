"""AI results remain experimental until independently reviewed and approved."""
from django.conf import settings
from django.db import models
from django.db.models import Q

# Active criteria for NEW assessments, votes and future presentation.
# Historical rows retain their original keys and are never reinterpreted.
FIVE_CRITERIA_VERSION = 'five_v1'
LEGACY_CRITERIA_VERSION = 'legacy9'
DIMENSIONS = [
    ('work_conditions_pressure', 'تعادل کار و زندگی و تناسب حجم کار'),
    ('management_environment', 'کیفیت مدیریت و محیط کاری'),
    ('growth_development', 'رشد و توسعه فردی و حرفه‌ای'),
    ('compensation_appreciation', 'جبران خدمات و فرهنگ قدردانی'),
    ('stability_security', 'ثبات و امنیت شغلی'),
]
LEGACY_DIMENSIONS = [
    ('work_life_balance','تعادل کار و زندگی'),
    ('workload','سبک‌بودن فشار کاری'),
    ('compensation_fairness','تناسب حقوق با حجم کار'),
    ('market_pay_competitiveness','رقابت‌پذیری حقوق در بازار'),
    ('micromanagement','نبود مدیریت ذره‌بینی'),
    ('decision_autonomy','استقلال تصمیم‌گیری'),
    ('direct_management','کیفیت مدیر مستقیم'),
    ('career_growth','رشد و یادگیری'),
    ('job_stability','امنیت شغلی'),
]
DIMENSION_CHOICES = DIMENSIONS + LEGACY_DIMENSIONS
CRITERIA_VERSIONS = [
    (LEGACY_CRITERIA_VERSION, '۹ معیار تاریخی - فقط سوابق'),
    (FIVE_CRITERIA_VERSION, '۵ معیار جدید'),
]

class AiAssessment(models.Model):
    experience = models.ForeignKey('experiences.PublicExperience', on_delete=models.PROTECT, related_name='ai_assessments')
    criteria_version = models.CharField(max_length=16, choices=CRITERIA_VERSIONS, default=FIVE_CRITERIA_VERSION)
    model_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=120)
    run_id = models.CharField(max_length=120)
    raw_payload = models.JSONField(default=dict)
    parse_status = models.CharField(max_length=30, default='unreviewed')
    independent_review_status = models.CharField(max_length=30, default='unreviewed')
    publish_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['experience','run_id'],name='wi_unique_ai_experience_run')]

class AiDimension(models.Model):
    assessment = models.ForeignKey(AiAssessment, on_delete=models.PROTECT, related_name='dimensions')
    key = models.CharField(max_length=60, choices=DIMENSION_CHOICES)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    evidence = models.JSONField(default=list)
    explanation = models.TextField(blank=True)
    semantic_status = models.CharField(max_length=32, default='unreviewed')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['assessment','key'],name='wi_unique_ai_dimension'),
            models.CheckConstraint(condition=Q(score__isnull=True) | (Q(score__gte=1) & Q(score__lte=10)),name='wi_ai_score_1_10'),
            models.CheckConstraint(condition=Q(confidence__gte=0) & Q(confidence__lte=100),name='wi_ai_confidence_0_100'),
        ]

class RatingSnapshot(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='rating_snapshots')
    source = models.CharField(max_length=8,choices=[('AI','تحلیل AI'),('USER','رأی کاربران')])
    dimension = models.CharField(max_length=60,choices=DIMENSION_CHOICES)
    captured_at = models.DateTimeField()
    supporting_count = models.PositiveIntegerField(default=0)
    experimental_mean = models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    publish_approved = models.BooleanField(default=False)
    provenance = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company','source','dimension','captured_at'],name='wi_unique_rating_snapshot')]


class AiHumanReviewEvent(models.Model):
    """Append-only *feasibility* judgments, not model approvals or public ratings.

    Reviews are explicitly tied to a single immutable AI dimension and reviewer.
    Existing AI scores, semantic_status and publish_approved are untouched.
    """
    VERDICTS = [
        ('supported', 'امتیاز دارای شواهد و تفسیر قابل قبول'),
        ('unsupported', 'امتیاز یا تفسیر نادرست / بدون پشتوانه'),
        ('correct_abstention', 'نبود امتیاز درست است؛ شاهد معنادار نیست'),
        ('missed_evidence', 'نبود امتیاز اشتباه است؛ شاهد وجود دارد'),
        ('uncertain', 'نیازمند بررسی بیشتر'),
    ]
    ERROR_TYPES = [
        ('', '— انتخاب علت خطا —'),
        ('wrong_company', 'انتساب اشتباه شرکت'),
        ('irrelevant_evidence', 'شاهد نامرتبط یا بدون پشتوانه'),
        ('wrong_dimension', 'دسته‌بندی نادرست شاخص'),
        ('wrong_polarity', 'جهت امتیاز برعکس تفسیر شده'),
        ('unsupported_score', 'امتیاز با شدت شاهد تناسب ندارد'),
        ('wrong_context_time', 'برداشت نادرست از زمان یا زمینه'),
        ('duplicate_independence', 'تکراری بودن یا استقلال نامشخص'),
        ('missed_signal', 'شاهد موجود از قلم افتاده'),
        ('other', 'علت دیگر'),
    ]
    dimension = models.ForeignKey(AiDimension, on_delete=models.PROTECT, related_name='human_review_events')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ai_feasibility_review_events')
    verdict = models.CharField(max_length=24, choices=VERDICTS)
    primary_error = models.CharField(max_length=32, choices=ERROR_TYPES, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        indexes = [models.Index(fields=['dimension', '-created_at'])]

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if self.pk is not None:
            errors['dimension'] = 'Human review decisions are append-only.'
        if not self.dimension_id:
            errors['dimension'] = 'Dimension is required.'
        elif self.verdict:
            score = self.dimension.score
            if score is None and self.verdict in {'supported', 'unsupported'}:
                errors['verdict'] = 'A missing AI score must be reviewed as abstention/missed evidence/uncertain.'
            if score is not None and self.verdict in {'correct_abstention', 'missed_evidence'}:
                errors['verdict'] = 'Abstention verdicts require a missing AI score.'
        if self.verdict in {'unsupported', 'missed_evidence'}:
            if not self.primary_error:
                errors['primary_error'] = 'An error category is required for an incorrect result.'
            if len(self.note.strip()) < 12:
                errors['note'] = 'Briefly explain the error (at least 12 characters).'
        elif self.primary_error:
            errors['primary_error'] = 'Only erroneous results have a primary error category.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('Human review events are append-only')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Human review events are append-only')
from .semantic_models_v17 import SemanticScoreOverride
