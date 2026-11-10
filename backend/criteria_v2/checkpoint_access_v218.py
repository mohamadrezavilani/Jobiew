"""Fail-closed authentication for private checkpoint previews.

DEBUG=True is allowed only on explicitly enabled local-development dashboards.
DEBUG=False staging requires a second distinct flag, exact staging hostname,
HTTPS, staff permissions, and the publication gate remaining disabled.
Never enable the staging flag on the public Jobiew host.
"""
import os
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http.request import validate_host
from .pilot_dashboard_v213 import _authorize, _PRIVATE_PERMISSIONS


def authorize_checkpoint(request):
    if settings.DEBUG:
        return _authorize(request)
    if (os.environ.get('JOBIEW_CHECKPOINT_STAGING_ENABLED', '0') != '1' or
        os.environ.get('JOBIEW_DUAL6_PUBLICATION_ENABLED', '0') != '0'):
        raise Http404('Private staging disabled')
    expected_host = os.environ.get('JOBIEW_CHECKPOINT_STAGING_HOST', '').strip().lower()
    public_host = os.environ.get('JOBIEW_CHECKPOINT_PUBLIC_HOST', '').strip().lower()
    actual_host = request.get_host().split(':')[0].lower()
    if (not expected_host or not public_host or expected_host == public_host or
            ':' in expected_host or '/' in expected_host or
            ':' in public_host or '/' in public_host or
            expected_host not in settings.ALLOWED_HOSTS or
            validate_host(public_host, settings.ALLOWED_HOSTS) or
            actual_host != expected_host or not request.is_secure()):
        raise Http404('Private staging must use its designated HTTPS hostname')
    user = request.user
    if not (user.is_authenticated and user.is_active and user.is_staff and
            all(user.has_perm(permission) for permission in _PRIVATE_PERMISSIONS)):
        raise PermissionDenied('Private checkpoint review permissions required')
