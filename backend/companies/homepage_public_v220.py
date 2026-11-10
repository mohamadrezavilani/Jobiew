"""Explicitly gated, reversible public homepage with released 6+6 scores.

The homepage shows only public numeric aggregates produced by the same
rights-cleared, fixed-snapshot gates as company profiles. No private records
or historical five_v1 scores are used.
"""
import os
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe
from . import views as company_views
from .homepage_preview_v219 import homepage_context, apply_homepage_headers
from criteria_v2.models import CriteriaCompanyReleaseEvent
from criteria_v2.publication_state_v231 import (
    company_publication_state, release_flags_enabled)



def home_or_directory(request):
    # Evaluated per-request for a reversible flag; default is the existing view.
    if os.environ.get('JOBIEW_HOMEPAGE_PUBLIC_ENABLED', '0') != '1':
        return company_views.index(request)
    return public_home(request)


@require_safe
def public_home(request):
    context = homepage_context(request)
    # Only released companies on this page are eligible for numeric public
    # aggregates. Do not query any unpublished checkpoint when flags are off.
    if release_flags_enabled():
        companies = list(context['page'].object_list)
        ids = [company.pk for company in companies]
        latest = {}
        for event in (CriteriaCompanyReleaseEvent.objects
                      .filter(company_id__in=ids)
                      .order_by('company_id', '-created_at', '-pk')):
            latest.setdefault(event.company_id, event)
        for company in companies:
            event = latest.get(company.pk)
            if event is None or event.decision != 'published':
                continue
            state = company_publication_state(company, release=event)
            summary = state['visible'].get(context['mode'])
            if state['visible_now'] and summary and summary['has_scores']:
                company.public_rating = summary
        # Retain exactly the page order and pagination decided by homepage_context.
        context['page'].object_list = companies
    context.update({
        'is_public_home': True,
        'homepage_action_url': reverse('company-index'),
        'company_directory_url': reverse('company-directory'),
    })
    response = render(request, 'companies/homepage_preview_v219.html', context)
    return apply_homepage_headers(response, private=False)
