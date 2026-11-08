"""Read-only historical review events and future scoring schema.

Classification decisions are created through the guarded staff queue. Existing
comments, old ratings, and source text are not editable here.
"""
from django.contrib import admin
from .models import CriteriaReviewEvent, CriteriaAnalysis, CriteriaAxisScore


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


@admin.register(CriteriaAnalysis)
class CriteriaAnalysisAdmin(AuditOnlyAdmin):
    list_display = ('experience', 'criteria_version', 'model_name', 'run_id', 'review_status')
    list_filter = ('criteria_version', 'review_status')


@admin.register(CriteriaAxisScore)
class CriteriaAxisScoreAdmin(AuditOnlyAdmin):
    list_display = ('analysis', 'key', 'score', 'semantic_status')
    list_filter = ('key', 'semantic_status')
