"""Read-only historical five-axis staff reports, strictly outside the v2 public system.

Restoring staff diagnostics is not an approval or a new score. The underlying
legacy views retain their own permission, request validation and no-store rules.
"""
import re
from companies.research_five_criteria_v7 import staff_five_criteria_preview
from companies.research_five_criteria_compare_v12 import staff_five_criteria_compare
from companies.research_five_criteria_analytics_v13 import staff_five_criteria_analytics

_BANNER = (
    '<aside role="note" class="wi-legacy-archive-banner" lang="fa" dir="rtl">'
    'آرشیو پژوهشی پنج‌معیاری (five_v1) — فقط برای بررسی تاریخی کارکنان. '
    'این امتیازها به معیارهای جدید شرایط کاری یا شرایط مصاحبه تبدیل نشده‌اند، '
    'در صفحات عمومی انتشار ندارند و برای امتیازدهی جدید معتبر نیستند.'
    '</aside>'
).encode('utf-8')


def _historical(response):
    if response.status_code == 200 and response.get('Content-Type', '').startswith('text/html'):
        old = response.content
        rendered = re.sub(rb'(<body\b[^>]*>)', lambda match: match.group(1) + _BANNER,
                          old, count=1, flags=re.IGNORECASE)
        response.content = rendered if rendered != old else _BANNER + old
        if response.has_header('Content-Length'):
            del response['Content-Length']
        response['X-Jobiew-Criteria-Archive'] = 'five_v1-read-only'
        response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


def historical_preview(request, pk):
    return _historical(staff_five_criteria_preview(request, pk))


def historical_compare(request):
    return _historical(staff_five_criteria_compare(request))


def historical_analytics(request):
    return _historical(staff_five_criteria_analytics(request))
