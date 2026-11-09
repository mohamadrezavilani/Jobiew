from django.urls import path
from . import views
from . import score_review_v209
from . import pilot_dashboard_v213
from . import pilot_company_v216
from . import checkpoint_private_v218

urlpatterns = [
    path('pilot/', pilot_dashboard_v213.index, name='dual-pilot-dashboard-v213'),
    path('checkpoint/', checkpoint_private_v218.index, name='dual-checkpoint-dashboard-v218'),
    path('checkpoint/companies/<str:pk>/', checkpoint_private_v218.company_preview, name='dual-checkpoint-company-v218'),
    path('checkpoint/<int:analysis_id>/', checkpoint_private_v218.detail, name='dual-checkpoint-detail-v218'),
    path('pilot/companies/<str:pk>/', pilot_company_v216.company_preview, name='dual-pilot-company-v216'),
    path('pilot/<int:analysis_id>/', pilot_dashboard_v213.detail, name='dual-pilot-detail-v213'),
    path('score-review/', score_review_v209.queue, name='dual-score-review-queue'),
    path('score-review/<int:analysis_id>/', score_review_v209.detail, name='dual-score-review-detail'),
    path('review-queue/', views.review_queue, name='dual-criteria-review-queue'),
    path('companies/<str:pk>/', views.private_company_framework, name='dual-criteria-company-internal'),
]
