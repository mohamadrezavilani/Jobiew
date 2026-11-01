from django.contrib import admin
from django.urls import path, reverse
from django.utils.html import format_html
from .review_dashboard_v47 import review_dashboard
from .pilot_review_queue_v48 import pilot_review_queue
from .models import Company, CompanyVerificationEvent


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'identity_status', 'tech_status', 'tehran_status',
                    'source_work_count', 'source_interview_count', 'vote_enabled', 'review_link')
    list_filter = ('identity_status', 'tech_status', 'tehran_status', 'vote_enabled')
    search_fields = ('display_name', 'source_url', 'source_name')
    readonly_fields = ('id', 'source_url', 'source_name', 'identity_status', 'tech_status',
                       'tehran_status', 'source_work_count', 'source_interview_count',
                       'vote_enabled', 'created_at', 'updated_at')
    list_per_page = 50
    change_form_template = 'admin/companies/company/change_form_v47.html'
    change_list_template = 'admin/companies/company/change_list_v48.html'

    def get_urls(self):
        return [
            path('pilot-review-queue/', self.admin_site.admin_view(self.pilot_queue_view),
                 name='companies_company_pilot_review_queue'),
            path('<path:object_id>/review/', self.admin_site.admin_view(self.review_view),
                 name='companies_company_review'),
        ] + super().get_urls()

    def pilot_queue_view(self, request):
        return pilot_review_queue(self, request)

    def review_view(self, request, object_id):
        return review_dashboard(self, request, object_id)

    @admin.display(description='بررسی و تأیید')
    def review_link(self, obj):
        return format_html('<a href="{}">داشبورد بررسی</a>',
                           reverse('admin:companies_company_review', args=[obj.pk]))

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context['wi_review_url'] = reverse('admin:companies_company_review', args=[object_id])
        return super().change_view(request, object_id, form_url, extra_context)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CompanyVerificationEvent)
class CompanyVerificationEventAdmin(admin.ModelAdmin):
    list_display = ('company', 'field', 'decision', 'reviewer', 'created_at')
    list_filter = ('field', 'decision', 'created_at')
    search_fields = ('company__display_name', 'company__source_url', 'rationale')
    readonly_fields = ('reviewer', 'created_at')
    exclude = ('reviewer',)
    autocomplete_fields = ('company',)

    def save_model(self, request, obj, form, change):
        if change:
            raise ValueError('Review history cannot be edited; create another decision.')
        obj.reviewer = request.user
        obj.save()

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
