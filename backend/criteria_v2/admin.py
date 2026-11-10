"""Read-only historical review events and future scoring schema.

Classification decisions are created through the guarded staff queue. Existing
comments, old ratings, and source text are not editable here.
"""
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import CriteriaReviewEvent, CriteriaAnalysis, CriteriaAxisScore, CriteriaScoreReviewEvent, CheckpointApprovalReceipt, CriteriaCompanyReleaseEvent, CriteriaClaudeComparison


class AuditOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(f.name for f in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CriteriaReviewEvent)
class CriteriaReviewEventAdmin(AuditOnlyAdmin):
    list_display = ('experience', 'source_kind', 'criteria_version', 'decision', 'reviewer', 'created_at')
    list_filter = ('source_kind', 'criteria_version', 'decision')
    search_fields = ('experience__source_url', 'experience__company__display_name', 'note')
    list_select_related = ('experience', 'reviewer')


class CriteriaAxisScoreInline(admin.TabularInline):
    model = CriteriaAxisScore
    extra = 0
    can_delete = False
    fields = ('key', 'score', 'confidence', 'evidence', 'explanation', 'semantic_status')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CriteriaAnalysis)
class CriteriaAnalysisAdmin(AuditOnlyAdmin):
    inlines = (CriteriaAxisScoreInline,)
    list_display = ('experience', 'criteria_version', 'model_name', 'run_id', 'review_status', 'review_company')

    @admin.display(description='بازبینی گروهی خصوصی')
    def review_company(self, obj):
        return format_html('<a href="{}">بازبینی شرکت</a>', reverse(
            'dual-checkpoint-bulk-v222', args=[obj.experience.company_id]))
    list_filter = ('criteria_version', 'review_status')


@admin.register(CriteriaAxisScore)
class CriteriaAxisScoreAdmin(AuditOnlyAdmin):
    list_display = ('analysis', 'key', 'score', 'semantic_status')
    list_filter = ('key', 'semantic_status')

@admin.register(CriteriaScoreReviewEvent)
class CriteriaScoreReviewEventAdmin(AuditOnlyAdmin):
    list_display = ('analysis', 'reviewer', 'created_at')
    list_select_related = ('analysis', 'reviewer')


@admin.register(CheckpointApprovalReceipt)
class CheckpointApprovalReceiptAdmin(AuditOnlyAdmin):
    list_display = ('analysis', 'reviewer', 'created_at')
    list_select_related = ('analysis', 'reviewer')


@admin.register(CriteriaCompanyReleaseEvent)
class CriteriaCompanyReleaseEventAdmin(AuditOnlyAdmin):
    list_display = ('company', 'decision', 'reviewer', 'created_at')
    list_filter = ('decision', 'created_at')
    list_select_related = ('company', 'reviewer')


@admin.register(CriteriaClaudeComparison)
class CriteriaClaudeComparisonAdmin(AuditOnlyAdmin):
    list_display = ('analysis', 'model_id', 'status', 'requested_by', 'created_at')
    list_filter = ('status', 'model_id')
    search_fields = ('analysis__experience__company__display_name',
                     'analysis__experience__source_url')
    list_select_related = ('analysis', 'requested_by')
