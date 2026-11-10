"""Small, task-oriented Django admin home. Historical records remain accessible.

Hiding a model from the index is NOT deletion or permission removal.
"""
import os
from django.contrib.admin import AdminSite


class JobiewAdminSite(AdminSite):
    site_header = 'مدیریت جابیو'
    site_title = 'پنل مدیریت جابیو'
    index_title = 'بررسی، تأیید و انتشار شرکت‌ها'
    index_template = 'admin/jobiew_index_v225.html'

    # Only primary operational models on the admin home. Historical legacy
    # AI, vote, and audit tables remain registered and retain their URLs.
    VISIBLE_MODELS = {
        'auth': {'user', 'group'},
        'companies': {'company', 'companyverificationevent'},
        'experiences': {'publicexperience', 'experiencereviewevent'},
        'criteria_v2': {'criteriaanalysis'},
        'locations': {'companylocationreviewevent'},
    }

    def index(self, request, extra_context=None):
        ctx = dict(extra_context or {})
        if (request.user.has_perm('companies.view_company')
                and request.user.has_perm('experiences.view_publicexperience')
                and request.user.has_perm('criteria_v2.view_criteriaanalysis')):
            from companies.models import Company
            from experiences.models import PublicExperience
            from criteria_v2.models import CriteriaAnalysis, CriteriaCompanyReleaseEvent
            from criteria_v2.checkpoint_contract_v218 import ENGINE
            from django.db.models import Count, Q
            counts = CriteriaAnalysis.objects.filter(
                raw_payload__engine=ENGINE).aggregate(
                    total=Count('pk'),
                    pending=Count('pk', filter=Q(review_status='pilot_unverified')),
                    reviewed=Count('pk', filter=Q(
                        review_status__in=('approved', 'no_evaluable_scores'))),
                )
            ctx['jw_counts'] = {
                'companies': Company.objects.count(),
                'experiences': PublicExperience.objects.count(),
                'checkpoint': counts['total'],
                'pending': counts['pending'],
                'reviewed': counts['reviewed'],
                'releases': CriteriaCompanyReleaseEvent.objects.count(),
            }
        return super().index(request, extra_context=ctx)

    def get_app_list(self, request, app_label=None):
        items = super().get_app_list(request, app_label)
        if os.environ.get('JOBIEW_ADMIN_FOCUSED_WORKFLOW_ENABLED', '1') != '1':
            return items
        output = []
        for app in items:
            allowed = self.VISIBLE_MODELS.get(app['app_label'])
            if not allowed:
                continue
            app = dict(app)
            app['models'] = [model for model in app['models']
                             if model['object_name'].lower() in allowed]
            if app['models']:
                output.append(app)
        return output
