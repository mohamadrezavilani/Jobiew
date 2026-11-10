from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import ExperienceReviewEvent, PublicExperience


@admin.register(PublicExperience)
class PublicExperienceAdmin(admin.ModelAdmin):
    list_display = ('company', 'source_kind', 'short_title', 'published_jalali',
                    'copyright_review', 'company_attribution_status', 'independence_status',
                    'review_six_and_claude')
    list_filter = ('source_kind', 'copyright_review', 'company_attribution_status', 'independence_status')
    search_fields = ('company__display_name', 'title', 'source_url')
    readonly_fields = tuple(f.name for f in PublicExperience._meta.fields)
    list_select_related = ('company',)
    list_per_page = 40

    @admin.display(description='عنوان')
    def short_title(self, obj):
        return obj.title[:90]

    @admin.display(description='متن، GPT-6 و Claude')
    def review_six_and_claude(self, obj):
        return format_html('<a href="{}">مشاهده و بررسی</a>',
                           reverse('admin:companies_company_experience_detail',
                                   args=[obj.company_id, obj.pk]))

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
