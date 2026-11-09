"""Human review and publication of derived five_v1 scores.

No verbatim source text is published by the public AI score views.
An unreviewed license status is tracked separately rather than becoming a
per-review admin chore; an explicit rights block still prevents publication.
Review and publication actions remain permission-checked and audited.
"""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from assessments.models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS, FIVE_CRITERIA_VERSION
from assessments.publication_workflow_v104 import (
    source_url, latest_verdict, publication_blockers, log_publication,
)
from experiences.models import PublicExperience, ExperienceReviewEvent

LABELS = dict(DIMENSIONS)


def preliminary_blockers(a):
    """Safety prerequisites independent of the five human decisions."""
    exp = a.experience
    company = exp.company
    problems = ['مدل پنج‌معیاری قدیمی بایگانی شده و انتشار جدید آن غیرفعال است.']  # jobiew_dual_framework_v200
    if a.criteria_version != FIVE_CRITERIA_VERSION or exp.source_kind != 'work':
        problems.append('فقط تجربهٔ کاری با مدل پنج‌شاخصی قابلیت انتشار دارد.')
    if company.identity_status != 'verified' or company.tech_status != 'verified':
        problems.append('هویت و فناوری‌بودن شرکت هنوز تأیید نشده است.')
    if exp.copyright_review == 'blocked':
        problems.append('برای این منبع منع صریح انتشار ثبت شده است.')
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
        elif not 1 <= dim.score <= 10 or not 0 <= dim.confidence <= 100:
            problems.append(f'امتیاز یا اطمینان «{LABELS[dim.key]}» نامعتبر است.')
        elif (not dim.evidence or not dim.explanation.strip()) and not (exp.body or '').strip():
            problems.append(f'متن اصلی برای تأیید دستی «{LABELS[dim.key]}» در دسترس نیست.')
        if dim.semantic_overrides.filter(status='active_provisional').exists():
            problems.append(f'اصلاح معنایی حل‌نشده برای «{LABELS[dim.key]}» وجود دارد.')
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
        # A 'pending' rights review is not a per-experience publish gate for
        # non-verbatim AI scores. A recorded explicit rights block is still a gate.
        if exp.copyright_review == 'blocked':
            raise ValueError('برای این منبع منع صریح انتشار ثبت شده است.')
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
        # The reviewer must have explicitly decided on each dimension first.
        # No automatic verdicts are created as a side effect of publishing.
        remaining = publication_blockers(a)
        if remaining:
            raise ValueError('؛ '.join(remaining))
        a.publish_approved = True
        a.independent_review_status = 'approved'
        a.save(update_fields=['publish_approved','independent_review_status'])
        log_publication(request, a, 'PUBLISH_APPROVED',
                        'پنج شاخص با تصمیم انسانی تأیید شدند؛ نتیجهٔ تحلیلی بدون متن خام انتشار یافت')
    return a


def save_dimension_decisions(request, assessment_pk, decisions):
    """Store five simple human yes/no choices; append-only, never fake a score.

    A 'no' is deliberately recorded as uncertain, because rejecting a suggestion
    without giving a reason is not proof that it is false or that evidence exists.
    """
    if not (request.user.is_staff and all(request.user.has_perm(p) for p in (
        'assessments.change_aiassessment', 'assessments.add_aihumanreviewevent',
        'experiences.view_publicexperience'))):
        raise PermissionDenied
    if set(decisions) != set(LABELS) or any(v not in {'yes', 'no'} for v in decisions.values()):
        raise ValueError('برای هر پنج شاخص فقط تأیید یا عدم تأیید انتخاب کن.')
    with transaction.atomic():
        a = (AiAssessment.objects.select_for_update().select_related('experience')
             .get(pk=assessment_pk))
        if a.criteria_version != FIVE_CRITERIA_VERSION or a.experience.source_kind != 'work':
            raise ValueError('فقط ارزیابی تجربهٔ کاری پنج‌شاخصی قابل بررسی است.')
        dims = list(a.dimensions.select_related('assessment').order_by('pk'))
        if len(dims) != 5 or {d.key for d in dims} != set(LABELS):
            raise ValueError('داده‌های پنج شاخص ناقص هستند؛ تصمیم ذخیره نشد.')
        changed = 0
        for dim in dims:
            decision = decisions[dim.key]
            wanted = ('supported' if dim.score is not None else 'correct_abstention') if decision == 'yes' else 'uncertain'
            prior = latest_verdict(dim)
            if prior and prior.verdict == wanted:
                continue
            note = ('متن اصلی تجربه و خروجی AI برای این شاخص توسط مدیر بررسی و تأیید شد؛ '
                    'در صورت فقدان شاهد ماشینی، تأیید فقط بر اساس مشاهده متن اصلی بوده است.'
                    if decision == 'yes' else 'این شاخص در بررسی مدیر برای انتشار تأیید نشد.')
            AiHumanReviewEvent.objects.create(
                dimension=dim, reviewer=request.user, verdict=wanted, note=note,
            )
            changed += 1
        if 'no' in decisions.values() and a.publish_approved:
            a.publish_approved = False
            a.independent_review_status = 'revoked'
            a.save(update_fields=['publish_approved', 'independent_review_status'])
            log_publication(request, a, 'PUBLICATION_REVOKED',
                            'مدیر یک یا چند شاخص را در بررسی مجدد تأیید نکرد')
    return changed
