from django.contrib import admin
from django.db.models import OuterRef, Subquery
from django.urls import reverse
from django.utils.html import format_html
from criteria_v2.checkpoint_contract_v218 import ENGINE
from criteria_v2.models import CriteriaAnalysis, ClaudeSixCheck
from .models import ExperienceReviewEvent, PublicExperience


@admin.register(PublicExperience)
class PublicExperienceAdmin(admin.ModelAdmin):
    list_display = ('company', 'source_kind', 'short_title', 'six_review_link',
                    'claude_review_link', 'source_review_summary')
    list_filter = ('source_kind', 'copyright_review', 'company_attribution_status', 'independence_status')
    search_fields = ('company__display_name', 'title', 'source_url')
    readonly_fields = tuple(f.name for f in PublicExperience._meta.fields)
    list_select_related = ('company',)
    list_per_page = 40

    def get_list_display(self, request):
        fields = list(self.list_display)
        allowed = all(request.user.has_perm(value) for value in (
            'companies.view_company', 'criteria_v2.view_criteriaanalysis',
            'criteria_v2.view_criteriaaxisscore'))
        if not allowed:
            fields.remove('six_review_link')
        if not allowed or not request.user.has_perm('criteria_v2.view_claudesixcheck'):
            fields.remove('claude_review_link')
        return tuple(fields)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        current = (CriteriaAnalysis.objects.filter(
            experience_id=OuterRef('pk'), raw_payload__engine=ENGINE,
            review_status__in=('pilot_unverified','approved','no_evaluable_scores'))
            .order_by('-created_at', '-pk'))
        queryset = queryset.annotate(
            current_six_id=Subquery(current.values('pk')[:1]))
        latest_claude = ClaudeSixCheck.objects.filter(
            analysis_id=OuterRef('current_six_id')).order_by('-created_at', '-pk')
        return queryset.annotate(
            saved_claude_status=Subquery(latest_claude.values('status')[:1]))

    @admin.display(description='عنوان')
    def short_title(self, obj):
        return obj.title[:90]

    @admin.display(description='مدارک')
    def source_review_summary(self, obj):
        ready = (obj.copyright_review == 'approved'
                 and obj.company_attribution_status == 'verified'
                 and obj.independence_status == 'verified')
        return 'سه تأیید ثبت شده' if ready else 'بررسی منبع ناقص'

    @admin.display(description='۶+۶')
    def six_review_link(self, obj):
        if not obj.current_six_id:
            return 'هنوز تحلیل ندارد'
        return format_html('<a href="{}">متن و شش معیار</a>',
            reverse('admin:companies_company_experience_detail',
                    args=[obj.company_id, obj.pk]))

    @admin.display(description='Claude مستقل')
    def claude_review_link(self, obj):
        if not obj.current_six_id:
            return '—'
        return format_html('<a href="{}">{}</a>',
            reverse('admin:companies_company_claude_six',
                    args=[obj.company_id, obj.pk]),
            'نمایش نتیجهٔ قبلی' if obj.saved_claude_status
            else 'بررسی اختیاری')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ExperienceReviewEvent)
class ExperienceReviewEventAdmin(admin.ModelAdmin):
    list_display = ('experience', 'review_field', 'decision', 'reviewer', 'created_at')
    list_filter = ('review_field', 'decision', 'created_at')
    search_fields = ('experience__source_url', 'experience__company__display_name', 'rationale')
    readonly_fields = ('reviewer', 'created_at')
    exclude = ('reviewer',)
    autocomplete_fields = ('experience',)

    def save_model(self, request, obj, form, change):
        if change:
            raise ValueError('Review history cannot be edited; create another decision.')
        obj.reviewer = request.user
        obj.save()

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
