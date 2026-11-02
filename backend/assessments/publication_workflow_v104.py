"""Explicitly approved five_v1 assessments only. Never expose crawler bodies.

Public output is re-gated on every request, so later rejections revoke visibility.
No database migrations; all decisions are audited in Django's append-only admin LogEntry.
"""
from __future__ import annotations
from collections import defaultdict
from statistics import mean
from urllib.parse import urlsplit

from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Prefetch

from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS, FIVE_CRITERIA_VERSION

DIM_KEYS = tuple(key for key, _ in DIMENSIONS)


def source_url(raw):
    try:
        url = urlsplit(raw or '')
        if url.scheme.lower() in {'http', 'https'} and url.hostname and not url.username and not url.password:
            return raw
    except ValueError:
        pass
    return ''


def latest_verdict(dimension):
    # Works with prefetch_related() without an N+1 query.
    rows = dimension.human_review_events.all()
    return rows[0] if rows else None


def publication_blockers(assessment, *, check_other=True):
    """Human-readable reasons to refuse publication; never treat AI confidence as approval."""
    exp = assessment.experience
    company = exp.company
    problems = []
    if assessment.criteria_version != FIVE_CRITERIA_VERSION:
        problems.append('فقط مدل پنج‌شاخصی جدید مجاز است.')
    if exp.source_kind != 'work':
        problems.append('مصاحبه در امتیازهای تجربه کاری وارد نمی‌شود.')
    if company.identity_status != 'verified' or company.tech_status != 'verified':
        problems.append('هویت و فناوری‌محور بودن شرکت باید در بررسی شرکت تأیید شود.')
    if exp.copyright_review != 'approved':
        problems.append('وضعیت حقوق استفاده از منبع باید تأیید شود.')
    if exp.company_attribution_status != 'verified':
        problems.append('انتساب تجربه به شرکت باید تأیید شود.')
    if exp.independence_status != 'verified':
        problems.append('مستقل و غیرتکراری‌بودن تجربه باید تأیید شود.')
    if assessment.parse_status.lower() in {'failed','validation_failed','partial','error','invalid'}:
        problems.append('نتیجه پردازش AI ناقص یا نامعتبر است.')
    payload = assessment.raw_payload if isinstance(assessment.raw_payload, dict) else {}
    digest = payload.get('source_content_sha256')
    if digest and str(digest).lower() != (exp.content_sha256 or '').lower():
        problems.append('متن منبع از زمان تحلیل AI تغییر کرده است.')
    dims = list(assessment.dimensions.all())
    keys = {d.key for d in dims}
    if keys != set(DIM_KEYS) or len(dims) != 5:
        problems.append('ارزیابی باید دقیقاً پنج شاخص اصلی داشته باشد.')
    if not any(d.score is not None for d in dims):
        problems.append('همهٔ شاخص‌ها فاقد امتیاز هستند؛ چیزی برای انتشار وجود ندارد.')
    for d in dims:
        if d.key not in DIM_KEYS:
            continue
        item = latest_verdict(d)
        expected = 'supported' if d.score is not None else 'correct_abstention'
        if not item or item.verdict != expected:
            problems.append('بازبینی انسانی «{}» هنوز تأیید نشده یا ناسازگار است.'.format(dict(DIMENSIONS)[d.key]))
        if d.score is not None:
            if not 1 <= d.score <= 10 or not 0 <= d.confidence <= 100:
                problems.append('نمره یا اطمینان خارج از دامنهٔ مجاز است.')
            if not d.evidence or not d.explanation.strip():
                problems.append('شاخص «{}» باید شاهد و توضیح معتبر داشته باشد.'.format(dict(DIMENSIONS)[d.key]))
            if d.semantic_overrides.filter(status='active_provisional').exists():
                problems.append('اصلاح معنایی فعالِ پژوهشی باید پیش از انتشار حل‌وفصل شود.')
        elif d.confidence != 0:
            problems.append('شاخص فاقد امتیاز باید اطمینان صفر داشته باشد.')
    if check_other and AiAssessment.objects.filter(experience_id=exp.pk, publish_approved=True).exclude(pk=assessment.pk).exists():
        problems.append('اجرای دیگری از همین تجربه قبلاً برای انتشار تأیید شده است.')
    return problems


def reviewed_assessments_for_company(company):
    """Only content approved by editor and still eligible; DB and human decisions may change."""
    qs = (AiAssessment.objects.filter(experience__company=company, publish_approved=True,
                                      independent_review_status='approved', criteria_version=FIVE_CRITERIA_VERSION)
          .select_related('experience','experience__company')
          .prefetch_related(Prefetch('dimensions',queryset=AiDimension.objects.prefetch_related(
              Prefetch('human_review_events',queryset=AiHumanReviewEvent.objects.order_by('-created_at','-pk')))))
          .order_by('-created_at','-pk'))
    seen = set()
    approved = []
    for assessment in qs:
        if assessment.experience_id in seen or publication_blockers(assessment, check_other=False):
            continue
        seen.add(assessment.experience_id)
        approved.append(assessment)
    return approved


def public_company_assessments(company, *, min_independent=3):
    """Distinct, verified review-level scores; company means only for >=3 experiences."""
    if min_independent < 3:
        raise ValueError('Minimum independent evidence is 3')
    assessments = reviewed_assessments_for_company(company)
    groups = defaultdict(list)
    cards = []
    for a in assessments:
        dims = {d.key: d for d in a.dimensions.all()}
        rows = []
        for key, label in DIMENSIONS:
            d = dims[key]
            if d.score is not None:
                groups[key].append(d.score)
            rows.append({'label':label,'score':d.score,'confidence':d.confidence})
        cards.append({'id':a.pk,'date':a.experience.published_jalali,
                      'source':source_url(a.experience.source_url),'dimensions':rows})
    summary = []
    for key, label in DIMENSIONS:
        scores = groups[key]
        summary.append({'key':key,'label':label,'count':len(scores),
                        'score':round(mean(scores),1) if len(scores)>=min_independent else None})
    return {'summary':summary,'cards':cards[:20],'approved_count':len(assessments),
            'has_summary':any(x['score'] is not None for x in summary)}


def log_publication(request, assessment, action, rationale):
    LogEntry.objects.create(
        user_id=request.user.pk,
        content_type=ContentType.objects.get_for_model(AiAssessment),
        object_id=str(assessment.pk),
        object_repr=f'AI assessment #{assessment.pk} / experience #{assessment.experience_id}'[:200],
        action_flag=CHANGE,
        change_message=f'{action} | {rationale}'[:1000],
    )


def set_publication(request, assessment_pk, *, approve, rationale):
    """Atomic gated approval/revocation. Permission is checked in caller and here."""
    if not (request.user.is_staff and request.user.has_perm('assessments.change_aiassessment')
            and request.user.has_perm('experiences.view_publicexperience')):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if len(rationale.strip()) < 12:
        raise ValueError('برای ثبت تصمیم باید حداقل ۱۲ حرف دلیل بنویسید.')
    with transaction.atomic():
        a = (AiAssessment.objects.select_for_update().select_related('experience','experience__company')
             .get(pk=assessment_pk))
        # Lock this experience as well, preventing two assessment versions from being approved concurrently.
        from experiences.models import PublicExperience
        PublicExperience.objects.select_for_update().get(pk=a.experience_id)
        if approve:
            blockers = publication_blockers(a)
            if blockers:
                raise ValueError(' '.join(blockers))
            a.publish_approved = True
            a.independent_review_status = 'approved'
            a.save(update_fields=['publish_approved','independent_review_status'])
            log_publication(request,a,'PUBLISH_APPROVED',rationale)
        else:
            a.publish_approved = False
            a.independent_review_status = 'revoked'
            a.save(update_fields=['publish_approved','independent_review_status'])
            log_publication(request,a,'PUBLICATION_REVOKED',rationale)
    return a
