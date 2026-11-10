"""Categorized, token-safe diagnostics for CSRF rejection behind a TLS proxy.

Never disable Django's CsrfViewMiddleware or reveal cookies, tokens, origin
values or CSRF secrets in application logs.
"""
import logging
from django.http import HttpResponseForbidden
from django.template.loader import render_to_string

logger = logging.getLogger('django.security.csrf')


def _category(reason):
    reason = str(reason).lower()
    if 'cookie not set' in reason:
        return 'COOKIE_NOT_SET'
    if 'csrf token missing' in reason:
        return 'TOKEN_MISSING'
    if 'csrf token from post' in reason or 'csrf token from the' in reason:
        return 'TOKEN_INVALID'
    if 'origin checking failed' in reason:
        return 'ORIGIN_MISMATCH'
    if 'referer checking failed' in reason or 'referer checking' in reason:
        return 'REFERER_MISMATCH'
    if 'referer' in reason:
        return 'REFERER_PROBLEM'
    return 'OTHER_CSRF_FAILURE'


def csrf_failure(request, reason=''):
    category = _category(reason)
    logger.warning('JOBIEW_CSRF_REJECTED category=%s secure=%s method=%s',
                   category, request.is_secure(), request.method)
    html = render_to_string('admin/jobiew_csrf_failure_v225.html', {
        'category': category,
    }, request=request)
    response = HttpResponseForbidden(html)
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'no-referrer'
    return response
