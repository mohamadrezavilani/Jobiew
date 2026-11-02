"""One-decision review for five_v1. Safe gates stay in place.

Source copyright needs evidence of permission, never assumed from public visibility.
Company verification is separate and cannot be fabricated from AI scores.
Creates audit records atomically and preserves all historical review events.
"""
from django.core.exceptions import PermissionDenied
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.db import transaction

from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS, FIVE_CRITERIA_VERSION
from assessments.publication_workflow_v104 import (
    source_url, latest_verdict, publication_blockers, log_publication,
)
from experiences.models import PublicExperience, ExperienceReviewEvent

LABELS = dict(DIMENSIONS)


def preliminary_blockers(a):
    """Only irreparable-on-this-button problems. Rights proof can be supplied inline."""
    exp = a.experience
    company = exp.company
    problems = []
    if a.criteria_version != FIVE_CRITERIA_VERSION or exp.source_kind != 'work':
        problems.append('فقط تجربهٔ کاری با مدل پنج‌شاخصی قابلیت انتشار دارد.')
    if company.identity_status != 'verified' or company.tech_status != 'verified':
        problems.append('هویت و فناوری‌بودن شرکت هنوز تأیید نشده است.')
    if exp.copyright_review not in {'approved', 'pending'}:
        problems.append('حقوق انتشار این تجربه رد شده یا نامعتبر است.')
    if exp.company_attribution_status not in {'verified', 'unverified'} or exp.independence_status not in {'verified', 'unknown'}:
        problems.append('انتساب یا مستقل‌بودن این نظر قبلاً رد شده یا وضعیت نامعتبری دارد.')
    if not source_url(exp.source_url):
        problems.append('نشانی اصلی منبع معتبر نیست.')
    if a.parse_status.lower() in {'failed', 'validation_failed', 'partial', 'error', 'invalid'}:
        problems.append('پردازش AI ناقص یا نامعتبر است.')
    payload = a.raw_payload if isinstance(a.raw_payload, dict) else {}
    digest = payload.get('source_content_sha256')
    if digest and str(digest).lower() != (exp.content_sha256 or '').lower():
        problems.append('متن تجربه پس از تحلیل AI تغییر کرده است.')
    dims = list(a.dimensions.all())
    if len(dims) != 5 or {d.key for d in dims} != set(LABELS):
        problems.append('ارزیابی پنج شاخص کامل نیست.')
    if not any(d.score is not None for d in dims):
        problems.append('این تجربه هیچ امتیازی برای انتشار ندارد.')
    for dim in dims:
        if dim.key not in LABELS:
            continue
        if dim.score is None:
            if dim.confidence != 0:
                problems.append(f'اطمینان شاخص بدون امتیاز «{LABELS[dim.key]}» باید صفر باشد.')
        elif not 1 <= dim.score <= 10 or not 0 <= dim.confidence <= 100 or not dim.evidence or not dim.explanation.strip():
            problems.append(f'شاهد یا دادهٔ معتبر برای «{LABELS[dim.key]}» ناقص است.')
        if dim.semantic_overrides.filter(status='active_provisional').exists():
            problems.append(f'اصلاح معنایی حل‌نشده برای «{LABELS[dim.key]}» وجود دارد.')
        old = latest_verdict(dim)
        expected = 'supported' if dim.score is not None else 'correct_abstention'
        if old and old.verdict != expected:
            problems.append(f'برای «{LABELS[dim.key]}» قبلاً ایراد یا ابهام ثبت شده است؛ ابتدا آن را بررسی کن.')
    if (exp.content_sha256 and PublicExperience.objects.filter(
            content_sha256=exp.content_sha256).exclude(pk=exp.pk).exists()):
        problems.append('متن یکسانی در رکورد دیگری وجود دارد؛ استقلال این تجربه باید بررسی شود.')
    if AiAssessment.objects.filter(experience_id=exp.pk, publish_approved=True).exclude(pk=a.pk).exists():
        problems.append('نسخهٔ دیگری از این تجربه قبلاً تأیید انتشار شده است.')
    return list(dict.fromkeys(problems))


def _check_permissions(request, *, publishing):
    perms = ['assessments.change_aiassessment', 'experiences.view_publicexperience']
    if publishing:
        perms += ['assessments.add_aihumanreviewevent', 'experiences.add_experiencereviewevent']
    if not request.user.is_staff or not all(request.user.has_perm(x) for x in perms):
        raise PermissionDenied


def quick_decision(request, assessment_pk, *, approve, rights_evidence_url=''):
    """A single administrator decision, with documented rights prerequisite.

    The user has inspected the company and narrative in the one-screen preview.
    For unknown attribution/independence the decision itself is recorded as
    an explicit human attestation, not as an inference by the AI.
    """
    _check_permissions(request, publishing=approve)
    with transaction.atomic():
        a = (AiAssessment.objects.select_for_update()
             .select_related('experience', 'experience__company').get(pk=assessment_pk))
        exp = PublicExperience.objects.select_for_update().get(pk=a.experience_id)
        a.experience = exp
        if not approve:
            a.publish_approved = False
            a.independent_review_status = 'rejected'
            a.save(update_fields=['publish_approved', 'independent_review_status'])
            log_publication(request, a, 'REVIEW_REJECTED', 'رد / نیازمند اصلاح با تصمیم انسانی در پنل ساده')
            return a
        if a.publish_approved:
            raise ValueError('این ارزیابی از قبل منتشر شده است.')
        blockers = preliminary_blockers(a)
        if blockers:
            raise ValueError('؛ '.join(blockers))
        if exp.copyright_review == 'pending':
            url = (rights_evidence_url or '').strip()
            if not url or url == exp.source_url:
                raise ValueError('برای منبع فاقد مجوز تأییدشده، نشانی سند مستقلِ اجازهٔ استفاده لازم است؛ لینک خود نظر کافی نیست.')
            try:
                URLValidator(schemes=['https', 'http'])(url)
            except ValidationError:
                raise ValueError('نشانی سند مجوز معتبر نیست.') from None
            ExperienceReviewEvent.objects.create(
                experience=exp, review_field='copyright', decision='approved',
                evidence_url=url, reviewer=request.user,
                rationale='مدیر مستند اجازهٔ استفاده و انتشار امتیازهای مبتنی بر این تجربه را بررسی و تأیید کرد.')
        exp.refresh_from_db()
        a.experience = exp
        evidence_link = source_url(exp.source_url)
        if exp.company_attribution_status == 'unverified':
            ExperienceReviewEvent.objects.create(
                experience=exp, review_field='attribution', decision='verified',
                evidence_url=evidence_link, reviewer=request.user,
                rationale='مدیر متن و صفحهٔ منبع را بررسی و انتساب نظر به شرکت نمایش‌داده‌شده را تأیید کرد.')
        if exp.independence_status == 'unknown':
            ExperienceReviewEvent.objects.create(
                experience=exp, review_field='independence', decision='verified',
                evidence_url=evidence_link, reviewer=request.user,
                rationale='مدیر تجربه را بررسی و پس از کنترل تکرار آشکار و تطبیق با منبع، آن را مستقل تأیید کرد.')
        exp.refresh_from_db()
        a.experience = exp
        for dim in a.dimensions.all():
            wanted = 'supported' if dim.score is not None else 'correct_abstention'
            old = latest_verdict(dim)
            if not old:
                AiHumanReviewEvent.objects.create(dimension=dim, reviewer=request.user, verdict=wanted)
        remaining = publication_blockers(a)
        if remaining:
            raise ValueError('؛ '.join(remaining))
        a.publish_approved = True
        a.independent_review_status = 'approved'
        a.save(update_fields=['publish_approved','independent_review_status'])
        log_publication(request, a, 'PUBLISH_APPROVED',
                        'یک تصمیم انسانی: بررسی متن، پنج شاخص، انتساب و استقلال؛ مجوز منبع ثبت شده است')
    return a
