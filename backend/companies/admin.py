from django.contrib import admin
from django.urls import path, reverse
from django.utils.html import format_html
from .review_dashboard_v47 import review_dashboard
from .company_experiences_admin_v103 import company_experiences, company_experience_detail
from .pilot_review_queue_v48 import pilot_review_queue
from .checkpoint_admin_queue_v225 import checkpoint_review_queue
from .quick_company_review_v226 import quick_company_review
from .provenance_bulk_review_v228 import provenance_review
from .workflow_v233 import company_workflow
from criteria_v2.claude_six_admin_v233 import company_claude_review
from criteria_v2.checkpoint_bulk_review_v222 import company_bulk_review
from criteria_v2.company_release_v224 import company_release
from .models import Company, CompanyVerificationEvent


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'verification_summary',
                    'source_work_count', 'source_interview_count',
                    'experiences_link', 'workflow_link')
    list_filter = ('identity_status', 'tech_status', 'tehran_status', 'vote_enabled')
    search_fields = ('display_name', 'source_url', 'source_name')
    readonly_fields = ('id', 'source_url', 'source_name', 'identity_status', 'tech_status',
                       'tehran_status', 'source_work_count', 'source_interview_count',
                       'vote_enabled', 'created_at', 'updated_at')
    list_per_page = 50
    change_form_template = 'admin/companies/company/change_form_v47.html'
    change_list_template = 'admin/companies/company/change_list_v48.html'

    def get_list_display(self, request):
        fields = list(self.list_display)
        if not request.user.has_perm('experiences.view_publicexperience'):
            fields.remove('experiences_link')
        if not (request.user.has_perm('criteria_v2.view_criteriaanalysis') and
                request.user.has_perm('experiences.view_publicexperience')):
            fields.remove('workflow_link')
        return tuple(fields)

    def get_urls(self):
        return [
            path('<path:object_id>/workflow/',
                 self.admin_site.admin_view(self.workflow_view),
                 name='companies_company_workflow'),
            path('checkpoints/', self.admin_site.admin_view(self.checkpoint_queue_view),
                 name='companies_company_checkpoint_queue'),
            path('<path:object_id>/checkpoint/verify/',
                 self.admin_site.admin_view(self.quick_company_review_view),
                 name='companies_company_checkpoint_verify'),
            path('<path:object_id>/checkpoint/bulk/',
                 self.admin_site.admin_view(self.checkpoint_bulk_view),
                 name='companies_company_checkpoint_bulk'),
            path('<path:object_id>/checkpoint/sources/',
                 self.admin_site.admin_view(self.checkpoint_sources_view),
                 name='companies_company_checkpoint_sources'),
            path('<path:object_id>/checkpoint/release/',
                 self.admin_site.admin_view(self.checkpoint_release_view),
                 name='companies_company_checkpoint_release'),
            path('<path:object_id>/experiences/<int:experience_id>/claude-six/',
                 self.admin_site.admin_view(self.claude_six_view),
                 name='companies_company_claude_six'),
            path('<path:object_id>/experiences/<int:experience_id>/',
                 self.admin_site.admin_view(self.experience_detail_view),
                 name='companies_company_experience_detail'),
            path('<path:object_id>/experiences/',
                 self.admin_site.admin_view(self.experiences_view),
                 name='companies_company_experiences'),
            path('pilot-review-queue/', self.admin_site.admin_view(self.pilot_queue_view),
                 name='companies_company_pilot_review_queue'),
            path('<path:object_id>/review/', self.admin_site.admin_view(self.review_view),
                 name='companies_company_review'),
        ] + super().get_urls()

    def workflow_view(self, request, object_id):
        return company_workflow(self, request, object_id)

    def claude_six_view(self, request, object_id, experience_id):
        return company_claude_review(self, request, object_id, experience_id)

    @admin.display(description='پیشرفت تأیید شرکت')
    def verification_summary(self, obj):
        identity = obj.identity_status == 'verified'
        tech = obj.tech_status == 'verified'
        return 'تأیید هویت و فناوری' if identity and tech else 'در انتظار بررسی شرکت'

    @admin.display(description='مسیر اصلی مدیریت')
    def workflow_link(self, obj):
        return format_html('<a href="{}">وضعیت و قدم بعدی</a>',
                           reverse('admin:companies_company_workflow', args=[obj.pk]))

    def quick_company_review_view(self, request, object_id):
        return quick_company_review(self, request, object_id)

    def checkpoint_queue_view(self, request):
        return checkpoint_review_queue(request)

    def checkpoint_bulk_view(self, request, object_id):
        return company_bulk_review(request, pk=object_id)

    def checkpoint_sources_view(self, request, object_id):
        return provenance_review(self, request, object_id)

    def checkpoint_release_view(self, request, object_id):
        return company_release(request, pk=object_id)

    @admin.display(description='تأیید گروهی GPT-6')
    def checkpoint_bulk_link(self, obj):
        return format_html('<a href="{}">بازبینی و تأیید</a>',
                           reverse('admin:companies_company_checkpoint_bulk', args=[obj.pk]))

    @admin.display(description='انتشار شرکت')
    def checkpoint_release_link(self, obj):
        return format_html('<a href="{}">انتشار / توقف</a>',
                           reverse('admin:companies_company_checkpoint_release', args=[obj.pk]))

    def experiences_view(self, request, object_id):
        return company_experiences(self, request, object_id)

    def experience_detail_view(self, request, object_id, experience_id):
        return company_experience_detail(self, request, object_id, experience_id)

    @admin.display(description='تجربه‌ها و مصاحبه‌ها')
    def experiences_link(self, obj):
        return format_html('<a href="{}">مشاهده نظرها</a>',
                           reverse('admin:companies_company_experiences', args=[obj.pk]))

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
        extra_context['wi_workflow_url'] = reverse('admin:companies_company_workflow', args=[object_id])
        extra_context['wi_review_url'] = reverse('admin:companies_company_review', args=[object_id])
        extra_context['wi_experiences_url'] = reverse('admin:companies_company_experiences', args=[object_id])
        extra_context['wi_can_see_experiences'] = request.user.has_perm('experiences.view_publicexperience')
        extra_context['wi_can_review_checkpoint'] = (
            request.user.has_perm('experiences.view_publicexperience') and
            request.user.has_perm('criteria_v2.view_criteriaanalysis'))
        extra_context['wi_checkpoint_bulk_url'] = reverse(
            'admin:companies_company_checkpoint_bulk', args=[object_id])
        extra_context['wi_checkpoint_verify_url'] = reverse(
            'admin:companies_company_checkpoint_verify', args=[object_id])
        extra_context['wi_checkpoint_sources_url'] = reverse(
            'admin:companies_company_checkpoint_sources', args=[object_id])
        extra_context['wi_checkpoint_release_url'] = reverse(
            'admin:companies_company_checkpoint_release', args=[object_id])
        if extra_context['wi_can_review_checkpoint']:
            from criteria_v2.publication_state_v231 import company_publication_state
            company = Company.objects.get(pk=object_id)
            extra_context['wi_score_state'] = company_publication_state(company)
            extra_context['wi_public_profile_url'] = reverse('company-detail', args=[object_id]) + '?tab=ai#dual-criteria'
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
