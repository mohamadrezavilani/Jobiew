"""Install Jobiew's focused back-office without unregistering historical models."""
from django.contrib.admin.apps import AdminConfig


class JobiewAdminConfig(AdminConfig):
    default_site = 'workplace_insights.admin_site.JobiewAdminSite'
