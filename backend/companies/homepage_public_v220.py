"""Explicitly gated, reversible public homepage cutover. OFF unless owner enables env.

Only public-listable Company metadata is rendered. Public scoring remains disabled.
The historical company directory remains accessible at /companies/ during any cutover.
"""
import os
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe
from . import views as company_views
from .homepage_preview_v219 import homepage_context, apply_homepage_headers


def home_or_directory(request):
    # Evaluated per-request for a reversible flag; default is the existing view.
    if os.environ.get('JOBIEW_HOMEPAGE_PUBLIC_ENABLED', '0') != '1':
        return company_views.index(request)
    return public_home(request)


@require_safe
def public_home(request):
    context = homepage_context(request)
    context.update({
        'is_public_home': True,
        'homepage_action_url': reverse('company-index'),
        'company_directory_url': reverse('company-directory'),
    })
    response = render(request, 'companies/homepage_preview_v219.html', context)
    return apply_homepage_headers(response, private=False)
