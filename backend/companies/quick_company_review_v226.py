"""Short, evidence-backed company verification workflow, without fabricated decisions.

The company source URL is a suggested evidence link only. Reviewer explicitly
checks each claim against that link (or replaces it with a stronger document).
No rights, individual-experience, geolocation or publication approvals are made.
"""
import hashlib
import json
from urllib.parse import urlsplit

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseNotAllowed

from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse




from .models import Company, CompanyVerificationEvent


class QuickVerificationForm(forms.Form):
    evidence_url = forms.URLField(
        label='لینک مدرکی که بررسی کردید', max_length=1500,
        widget=forms.URLInput(attrs={'size': 76, 'placeholder': 'https://...'}),
    )
    verify_identity = forms.BooleanField(
        required=False, label='هویت و نام این شرکت را در مدرک بررسی و تأیید کردم')
    verify_tech = forms.BooleanField(
        required=False, label='فعالیت فناوری این شرکت را در مدرک بررسی و تأیید کردم')
    confirm_evidence = forms.BooleanField(
        required=True, label='مدرک را واقعاً مشاهده کردم؛ صرف وجود لینک به معنای تأیید نیست')

    def clean(self):
        data = super().clean()
        if not data.get('verify_identity') and not data.get('verify_tech'):
            raise forms.ValidationError('حداقل یک مورد را پس از بررسی انتخاب کنید.')
        link = data.get('evidence_url', '')
        if link:
            parts = urlsplit(link)
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
                self.add_error('evidence_url', 'فقط لینک HTTPS بدون اطلاعات ورود معتبر است.')
        return data


def _safe_suggested_link(raw):
    try:
        parts = urlsplit(raw or '')
        if parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password:
            return raw
    except (TypeError, ValueError):
        pass
    return ''


def _snapshot(company):
    payload = (company.pk, company.identity_status, company.tech_status,
               company.source_url,
               tuple(CompanyVerificationEvent.objects.filter(company=company,
                       field__in=('identity','tech'))
                     .order_by('field', '-created_at', '-pk')
                     .values_list('field', 'decision', 'evidence_url', 'created_at')))
    return hashlib.sha256(json.dumps(payload, default=str,
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def quick_company_review(admin_view, request, object_id):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    company = get_object_or_404(Company, pk=object_id)
    if not admin_view.has_view_permission(request, company):
        raise PermissionDenied
    if not request.user.has_perm('companies.add_companyverificationevent'):
        raise PermissionDenied('Company verification permission required')
    snapshot = _snapshot(company)
    initial = {'evidence_url': _safe_suggested_link(company.source_url)}
    form = QuickVerificationForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        if request.POST.get('snapshot') != snapshot:
            return HttpResponse('COMPANY_VERIFICATION_STALE_RELOAD', status=409)
        with transaction.atomic():
            company = Company.objects.select_for_update().get(pk=object_id)
            if _snapshot(company) != snapshot:
                return HttpResponse('COMPANY_VERIFICATION_STALE_RELOAD', status=409)
            checked = []
            for field, flag, status_field, reason in [
                ('identity', 'verify_identity', 'identity_status',
                 'هویت و نام شرکت را با مطالعهٔ مدرک اعلام‌شده بررسی کردم.'),
                ('tech', 'verify_tech', 'tech_status',
                 'فعالیت فناوری شرکت را با مطالعهٔ مدرک اعلام‌شده بررسی کردم.'),
            ]:
                if not form.cleaned_data[flag] or getattr(company, status_field) == 'verified':
                    continue
                CompanyVerificationEvent.objects.create(
                    company=company, reviewer=request.user, field=field,
                    decision='verified', evidence_url=form.cleaned_data['evidence_url'],
                    rationale=reason,
                )
                checked.append(field)
        messages.success(request,
            'بررسی ' + (' و '.join(checked) if checked else 'قبلاً ثبت‌شده') +
            ' ثبت شد. مجوز انتشار تجربه‌ها و نمره‌ها تغییری نکرد.')
        return redirect('admin:companies_company_checkpoint_release', object_id=company.pk)
    response = TemplateResponse(request, 'admin/companies/company/quick_review_v226.html', {
        **admin_view.admin_site.each_context(request),
        'title': 'تأیید سریع شرکت: ' + company.display_name,
        'company': company, 'form': form, 'snapshot': snapshot,
        'suggested_url': initial['evidence_url'],
        'release_url': reverse('admin:companies_company_checkpoint_release', args=[company.pk]),
        'opts': admin_view.model._meta,
        'has_view_permission': True,
    })
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Referrer-Policy'] = 'same-origin'
    return response
