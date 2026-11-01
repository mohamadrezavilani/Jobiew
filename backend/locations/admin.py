"""View-only map data: map publication awaits a source-backed review workflow."""
from django.contrib import admin
from .models import CompanyLocation


@admin.register(CompanyLocation)
class CompanyLocationAdmin(admin.ModelAdmin):
    list_display = ('company', 'verification_status', 'evidence_url')
    list_filter = ('verification_status',)
    search_fields = ('company__display_name',)
    readonly_fields = tuple(f.name for f in CompanyLocation._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from .models import CompanyLocationReviewEvent


@admin.register(CompanyLocationReviewEvent)
class CompanyLocationReviewEventAdmin(admin.ModelAdmin):
    change_form_template = 'admin/locations/companylocationreviewevent/change_form.html'
    list_display = ('company', 'decision', 'evidence_url', 'reviewer', 'created_at')
    list_filter = ('decision', 'created_at')
    search_fields = ('company__display_name', 'company__source_url', 'rationale')
    autocomplete_fields = ('company',)
    exclude = ('reviewer',)
    readonly_fields = ('created_at',)
    list_per_page = 50

    def save_model(self, request, obj, form, change):
        if change:
            raise ValueError('Location review events cannot be edited.')
        obj.reviewer = request.user
        obj.save()

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
