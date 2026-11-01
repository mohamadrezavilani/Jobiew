"""Read-only AI audit data; admin cannot approve unreviewed AI ratings for publication."""
from django.contrib import admin
from django.urls import path
from .review_workspace_v53 import ai_feasibility_review
from .models import AiAssessment, AiDimension, RatingSnapshot, AiHumanReviewEvent


class _ReadOnlyAuditAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(f.name for f in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AiAssessment)
class AiAssessmentAdmin(_ReadOnlyAuditAdmin):
    change_list_template = 'admin/assessments/aiassessment/change_list_v53.html'
    list_display = ('experience', 'criteria_version', 'model_name', 'prompt_version', 'parse_status',
                    'independent_review_status', 'publish_approved')
    list_filter = ('criteria_version', 'parse_status', 'independent_review_status', 'publish_approved')
    search_fields = ('experience__source_url', 'experience__company__display_name', 'run_id')
    list_select_related = ('experience', 'experience__company')

    def get_urls(self):
        return [path('feasibility-review/', self.admin_site.admin_view(self.feasibility_view),
                     name='assessments_aiassessment_feasibility_review')] + super().get_urls()

    def feasibility_view(self, request):
        return ai_feasibility_review(self, request)


@admin.register(AiDimension)
class AiDimensionAdmin(_ReadOnlyAuditAdmin):
    list_display = ('assessment', 'key', 'score', 'confidence', 'semantic_status')
    list_filter = ('key', 'semantic_status')


@admin.register(RatingSnapshot)
class RatingSnapshotAdmin(_ReadOnlyAuditAdmin):
    list_display = ('company', 'source', 'dimension', 'captured_at', 'supporting_count', 'publish_approved')
    list_filter = ('source', 'publish_approved')


@admin.register(AiHumanReviewEvent)
class AiHumanReviewEventAdmin(_ReadOnlyAuditAdmin):
    list_display = ('dimension', 'verdict', 'primary_error', 'reviewer', 'created_at')
    list_filter = ('verdict', 'primary_error', 'created_at')
    search_fields = ('dimension__assessment__experience__company__display_name',
                     'dimension__assessment__experience__source_url', 'note')
    list_select_related = ('dimension', 'reviewer')
