"""One-company editorial review dashboard.

Only existing append-only review models perform writes; status columns and
map-visible locations are never updated directly by this view.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from companies.models import Company, CompanyVerificationEvent
from locations.models import CompanyLocation, CompanyLocationReviewEvent
from companies.map_visibility_v232 import company_map_status


class CompanyDecisionForm(forms.ModelForm):
    class Meta:
        model = CompanyVerificationEvent
        fields = ('decision', 'evidence_url', 'rationale')
        labels = {
            'decision': 'تصمیم', 'evidence_url': 'لینک مدرک',
            'rationale': 'دلیل بررسی',
        }
        widgets = {'rationale': forms.Textarea(attrs={'rows': 2})}


class LocationDecisionForm(forms.ModelForm):
    class Meta:
        model = CompanyLocationReviewEvent
        fields = ('decision', 'address', 'latitude', 'longitude', 'evidence_url', 'rationale')
        labels = {
            'decision': 'تصمیم مکان', 'address': 'آدرس دفتر',
            'latitude': 'عرض جغرافیایی', 'longitude': 'طول جغرافیایی',
            'evidence_url': 'لینک منبع نشانی دفتر', 'rationale': 'دلیل بررسی',
        }
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'rationale': forms.Textarea(attrs={'rows': 2}),
        }


def review_dashboard(admin_view, request, object_id):
    """Bound as a CompanyAdmin URL, protected by admin_site.admin_view."""
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied

    can_company = request.user.has_perm('companies.add_companyverificationevent')
    can_location = request.user.has_perm('locations.add_companylocationreviewevent')
    field_info = dict(CompanyVerificationEvent.FIELD_CHOICES)
    columns = {
        'identity': 'identity_status',
        'tech': 'tech_status',
        'tehran': 'tehran_status',
    }
    company_events = list(company.verification_events.select_related('reviewer').order_by('-created_at', '-pk')[:30])
    location_events = list(company.location_review_events.select_related('reviewer').order_by('-created_at', '-pk')[:10])
    # Look up the latest review of EACH dimension independently. Otherwise an
    # active field could hide another field's last decision from the dashboard.
    latest = {field: company.verification_events.select_related('reviewer').filter(field=field).first()
              for field in columns}
    loc_latest = location_events[0] if location_events else None
    location = CompanyLocation.objects.filter(company=company).first()

    # Review events remain append-only, but editors need to see their last saved
    # values. Non-verified location coordinates are archival, not public evidence.
    initial_location = {}
    if location:
        initial_location = {
            'address': location.address,
            'latitude': location.latitude,
            'longitude': location.longitude,
            'evidence_url': location.evidence_url,
        }
    if loc_latest:
        initial_location['decision'] = loc_latest.decision
        initial_location['rationale'] = loc_latest.rationale
        # A positive decision is the exact source of the current map coordinates.
        if loc_latest.decision == 'verified':
            initial_location.update({
                'address': loc_latest.address,
                'latitude': loc_latest.latitude,
                'longitude': loc_latest.longitude,
                'evidence_url': loc_latest.evidence_url,
            })
        else:
            # Do not mislabel a previous approval's URL as evidence supplied
            # in the most recent rejection/unverification event.
            initial_location['evidence_url'] = loc_latest.evidence_url
    selected_field = None
    location_posted = False
    company_bound = None
    location_bound = None
    if request.method == 'POST':
        kind = request.POST.get('review_kind')
        if kind == 'company':
            if not can_company:
                raise PermissionDenied
            selected_field = request.POST.get('verification_field')
            if selected_field not in columns:
                raise Http404('Unknown verification field')
            instance = CompanyVerificationEvent(
                company=company, field=selected_field, reviewer=request.user,
            )
            company_bound = CompanyDecisionForm(
                request.POST, instance=instance, prefix=f'verification-{selected_field}',
            )
            if company_bound.is_valid():
                company_bound.save()
                messages.success(request, f'تصمیم «{field_info[selected_field]}» ثبت شد.')
                return HttpResponseRedirect(reverse('admin:companies_company_review', args=[company.pk]))
        elif kind == 'location':
            if not can_location:
                raise PermissionDenied
            location_posted = True
            instance = CompanyLocationReviewEvent(company=company, reviewer=request.user)
            location_bound = LocationDecisionForm(request.POST, instance=instance)
            if location_bound.is_valid():
                location_bound.save()
                messages.success(request, 'تصمیم مکان شرکت ثبت شد.')
                return HttpResponseRedirect(reverse('admin:companies_company_review', args=[company.pk]))
        else:
            raise Http404('Unknown review action')

    panels = []
    decision_labels = dict(CompanyVerificationEvent._meta.get_field('decision').choices)
    for field, column in columns.items():
        if selected_field == field and company_bound is not None:
            form = company_bound
        else:
            saved = latest.get(field)
            initial = ({
                'decision': saved.decision,
                'evidence_url': saved.evidence_url,
                'rationale': saved.rationale,
            } if saved else {})
            form = CompanyDecisionForm(
                instance=CompanyVerificationEvent(company=company, reviewer=request.user, field=field),
                prefix=f'verification-{field}', initial=initial,
            )
        panels.append({
            'field': field, 'title': field_info[field], 'status': getattr(company, column),
            'status_label': decision_labels.get(getattr(company, column), 'نامشخص'),
            'latest': latest.get(field), 'form': form,
        })

    loc_form = location_bound if location_posted else LocationDecisionForm(
        instance=CompanyLocationReviewEvent(company=company, reviewer=request.user),
        initial=initial_location,
    )
    loc_status = location.verification_status if location else 'unverified'
    map_status = company_map_status(company, location=location, latest_event=loc_latest)
    eligible = map_status['visible']
    recent = sorted([*company_events[:8], *location_events[:8]],
                    key=lambda x: (x.created_at, x.pk), reverse=True)[:12]
    ctx = {
        **admin_view.admin_site.each_context(request),
        'title': f'بررسی شرکت: {company.display_name}',
        'company': company, 'panels': panels, 'location_form': loc_form,
        'can_see_experiences': request.user.has_perm('experiences.view_publicexperience'),
        'location': location, 'location_latest': loc_latest,
        'loc_status': loc_status,
        'loc_status_label': dict(CompanyLocationReviewEvent.DECISIONS).get(loc_status),
        'location_is_archived': bool(location and loc_status != 'verified' and
                                     (location.latitude is not None or location.longitude is not None)),
        'can_company_review': can_company,
        'can_location_review': can_location,
        'public_map_eligible': eligible,
        'public_map_checks': map_status['checks'],
        'public_map_missing': map_status['missing'],
        'public_map_consistent': map_status['consistent'],
        'recent_events': recent,
        'company_search_url': 'https://www.google.com/search?q=' + quote_plus(company.display_name + ' تماس با ما آدرس رسمی'),
        'opts': admin_view.model._meta,
        'has_view_permission': True,
    }
    return TemplateResponse(request, 'admin/companies/company/review_dashboard_v47.html', ctx)
