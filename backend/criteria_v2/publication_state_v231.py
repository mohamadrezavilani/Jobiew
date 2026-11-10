"""One consistent public-score state for company cards and staff dashboards.

Only an explicitly published immutable score snapshot may appear in public
views. Never expose source bodies, quotes, private proposal counts or legacy
five_v1 model results via this module.
"""
import os
from decimal import Decimal, ROUND_HALF_UP

from .models import CriteriaCompanyReleaseEvent
from .sufficiency_v208 import company_public_sufficiency, publication_enabled


def release_flags_enabled():
    return (
        publication_enabled()
        and os.environ.get('JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED', '0') == '1'
        and os.environ.get('JOBIEW_COMPANY_RELEASE_ONLY_ENABLED', '0') == '1'
    )


def _scope_summary(scope):
    scored = [axis['score'] for axis in scope['axes'] if axis['score'] is not None]
    # Equal-weight mean of available axis averages, not a company-wide
    # population rating; explicitly label this limitation on the homepage.
    average = None
    if scored:
        average = float((sum(Decimal(str(value)) for value in scored)
                         / Decimal(len(scored))).quantize(
                             Decimal('0.1'), rounding=ROUND_HALF_UP))
    return {
        'has_scores': bool(scored),
        'average': average,
        'scored_axes': len(scored),
        'coverage': scope.get('used_experience_count', 0),
        'scope': scope,
    }


def company_publication_state(company, *, release=None):
    """Live, permission-independent publication gates, all checked on reads.

    release can be passed by callers that already fetched the latest event.
    This returns only numeric public aggregates, not personal/source text.
    """
    if release is None:
        release = (CriteriaCompanyReleaseEvent.objects.filter(
            company=company).order_by('-created_at', '-pk').first())
    enabled = release_flags_enabled()
    recorded_count = (len(release.approved_runs)
                      if release is not None and release.decision == 'published'
                      and isinstance(release.approved_runs, dict) else 0)
    is_published = bool(release is not None and release.decision == 'published')
    visible = {'work': None, 'interview': None}
    if enabled and is_published and recorded_count:
        data = company_public_sufficiency(company)
        visible = {kind: _scope_summary(scope) for kind, scope in data.items()}
    used_count = sum((summary['coverage'] if summary else 0)
                     for summary in visible.values())
    if release is None:
        reason = 'هنوز تصمیم انتشار این شرکت ثبت نشده است.'
    elif not is_published:
        reason = 'نمایش امتیازهای این شرکت با تصمیم مدیر متوقف شده است.'
    elif not enabled:
        reason = 'تصمیم انتشار ثبت شده، اما کلیدهای نمایش عمومی غیرفعال هستند.'
    elif used_count == 0:
        reason = ('تصمیم انتشار ثبت شده، ولی هیچ امتیازی از کنترل‌های زندهٔ '
                  'شواهد و کیفیت برای نمایش عمومی عبور نمی‌کند.')
    else:
        reason = 'امتیازهای تأییدشده در پروفایل عمومی و کارت‌های صفحهٔ اصلی قابل نمایش‌اند.'
    return {
        'release': release,
        'recorded_count': recorded_count,
        'is_published': is_published,
        'flags_enabled': enabled,
        'visible': visible,
        'visible_experiences': used_count,
        'visible_now': used_count > 0,
        'reason': reason,
    }
