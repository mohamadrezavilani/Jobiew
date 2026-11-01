"""Staff-only review UI and unbiased aggregate *observations* for feasibility.

Observations are NOT publication approvals. In particular, an AI score supported
by one reviewer does not imply enough independent experiences for company scores.
"""
from __future__ import annotations

from collections import Counter
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import urlencode

from .models import AiAssessment, AiDimension, AiHumanReviewEvent, DIMENSIONS, LEGACY_DIMENSIONS, LEGACY_CRITERIA_VERSION


class HumanVerdictForm(forms.Form):
    verdict = forms.ChoiceField(choices=[('', '— انتخاب نتیجه بررسی —'), *AiHumanReviewEvent.VERDICTS],
                                label='نتیجه بررسی', required=True)
    primary_error = forms.ChoiceField(choices=AiHumanReviewEvent.ERROR_TYPES,
                                      label='علت اصلی خطا', required=False)
    note = forms.CharField(label='دلیل / شاهد بررسی', required=False,
                            widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'برای نتیجه نادرست، توضیح کوتاه الزامی است'}))
    acknowledged_source = forms.BooleanField(label='متن اصلی را بررسی کرده‌ام', required=True)

    def __init__(self, *args, dimension: AiDimension, **kwargs):
        super().__init__(*args, **kwargs)
        self.dimension = dimension

    def clean(self):
        data = super().clean()
        verdict = data.get('verdict')
        score = self.dimension.score
        if verdict in {'supported', 'unsupported'} and score is None:
            self.add_error('verdict', 'این شاخص امتیاز ندارد؛ گزینه مخصوص نبود امتیاز را انتخاب کنید.')
        if verdict in {'correct_abstention', 'missed_evidence'} and score is not None:
            self.add_error('verdict', 'این شاخص امتیاز دارد؛ گزینه بررسی امتیاز را انتخاب کنید.')
        if verdict in {'unsupported', 'missed_evidence'}:
            if not data.get('primary_error'):
                self.add_error('primary_error', 'نوع خطا را انتخاب کنید.')
            if len((data.get('note') or '').strip()) < 12:
                self.add_error('note', 'توضیح خطا باید حداقل ۱۲ حرف باشد.')
        elif data.get('primary_error'):
            self.add_error('primary_error', 'برای نتیجه بدون خطا، علت خطا را خالی بگذارید.')
        return data


def latest_review_map(dimensions):
    """Latest event globally, not just from one reviewer; preserve older events."""
    return {dim.pk: next(iter(dim.human_review_events.all()), None) for dim in dimensions}


def build_metrics(assessments):
    """Count ONLY the latest human review per dimension. Never count uncertain as correct."""
    stats = {key: Counter() for key, _ in [*LEGACY_DIMENSIONS, *DIMENSIONS]}
    examples = Counter()
    latest_count = 0
    for assessment in assessments:
        examples['assessments'] += 1
        for dim in assessment.dimensions.all():
            examples['dimensions'] += 1
            latest = next(iter(dim.human_review_events.all()), None)
            if latest is None:
                continue
            stats[dim.key][latest.verdict] += 1
            latest_count += 1
    rows = []
    for key, label in [*LEGACY_DIMENSIONS, *DIMENSIONS]:
        c = stats[key]
        decisive = c['supported'] + c['unsupported'] + c['correct_abstention'] + c['missed_evidence']
        errors = c['unsupported'] + c['missed_evidence']
        rows.append({'key': key, 'label': label,
                     'reviewed': sum(c.values()), 'decisive': decisive,
                     'supported': c['supported'], 'correct_abstention': c['correct_abstention'],
                     'unsupported': c['unsupported'], 'missed_evidence': c['missed_evidence'],
                     'uncertain': c['uncertain'],
                     'error_count': errors,
                     'observed_error_pct': round(100 * errors / decisive, 1) if decisive else None})
    return rows, {'assessments': examples['assessments'], 'dimensions': examples['dimensions'],
                  'reviewed': latest_count, 'unreviewed': examples['dimensions'] - latest_count}


def ai_feasibility_review(admin_view, request):
    if not admin_view.has_view_permission(request):
        raise PermissionDenied
    can_write = request.user.has_perm('assessments.add_aihumanreviewevent')
    selected = request.GET.get('assessment') or ''
    assessment_qs = AiAssessment.objects.filter(experience__source_kind='work').select_related(
        'experience', 'experience__company').prefetch_related(
            Prefetch('dimensions', queryset=AiDimension.objects.order_by('pk').prefetch_related(
                Prefetch('human_review_events', queryset=AiHumanReviewEvent.objects.select_related('reviewer').order_by('-created_at', '-pk')))))
    assessments = list(assessment_qs.order_by('pk'))
    by_id = {str(a.pk): a for a in assessments}
    if selected and selected not in by_id:
        raise Http404('Assessment is not part of the work-experience audit')
    active = by_id.get(selected) if selected else (assessments[0] if assessments else None)
    invalid_form = None
    invalid_dim_id = None
    if request.method == 'POST':
        if not can_write:
            raise PermissionDenied
        id_from_post = request.POST.get('assessment_id')
        if id_from_post not in by_id or active is None or str(active.pk) != id_from_post:
            raise Http404('Invalid assessment')
        try:
            dim_id = int(request.POST.get('dimension_id') or '')
        except (TypeError, ValueError):
            raise Http404('Invalid dimension')
        dimension = next((dim for dim in active.dimensions.all() if dim.pk == dim_id), None)
        if dimension is None:
            raise Http404('Dimension does not belong to this assessment')
        form = HumanVerdictForm(request.POST, dimension=dimension)
        if form.is_valid():
            AiHumanReviewEvent.objects.create(
                dimension=dimension, reviewer=request.user,
                verdict=form.cleaned_data['verdict'],
                primary_error=form.cleaned_data.get('primary_error') or '',
                note=form.cleaned_data.get('note') or '')
            messages.success(request, 'نتیجه بررسی انسانی ثبت شد؛ خروجی اصلی AI بدون تغییر باقی ماند.')
            url = reverse('admin:assessments_aiassessment_feasibility_review')
            return HttpResponseRedirect(url + '?' + urlencode({'assessment': active.pk}) + f'#dimension-{dimension.key}')
        invalid_form = form
        invalid_dim_id = dim_id

    labels = dict([*LEGACY_DIMENSIONS, *DIMENSIONS])
    panels = []
    if active:
        by_key = {dim.key: dim for dim in active.dimensions.all()}
        criteria = LEGACY_DIMENSIONS if active.criteria_version == LEGACY_CRITERIA_VERSION else DIMENSIONS
        for key, label in criteria:
            dim = by_key.get(key)
            latest = next(iter(dim.human_review_events.all()), None) if dim else None
            form = (invalid_form if dim and dim.pk == invalid_dim_id else
                    HumanVerdictForm(dimension=dim) if dim and can_write else None)
            panels.append({'key': key, 'label': label, 'dim': dim, 'latest': latest,
                           'form': form})
    rows, totals = build_metrics(assessments)
    ctx = {
        **admin_view.admin_site.each_context(request),
        'title': 'اعتبارسنجی انسانی استخراج AI — آزمایش امکان‌سنجی',
        'opts': admin_view.model._meta, 'has_view_permission': True,
        'assessments': assessments, 'active': active, 'panels': panels,
        'metrics': rows, 'totals': totals, 'can_write': can_write,
        'verdict_labels': dict(AiHumanReviewEvent.VERDICTS),
        'other_reviewers_notice': 'این نتایج صرفاً بازبینی انسانی محدودند؛ تأیید انتشار یا دقت آماری برای همه شرکت‌ها نیستند.',
    }
    response = TemplateResponse(request, 'admin/assessments/aiassessment/feasibility_review_v53.html', ctx)
    patch_cache_control(response, private=True, no_store=True)
    return response
