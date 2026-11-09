from django.urls import path
from . import views
from . import score_review_v209
from . import pilot_dashboard_v213

urlpatterns = [
    path('pilot/', pilot_dashboard_v213.index, name='dual-pilot-dashboard-v213'),
    path('pilot/<int:analysis_id>/', pilot_dashboard_v213.detail, name='dual-pilot-detail-v213'),
    path('score-review/', score_review_v209.queue, name='dual-score-review-queue'),
    path('score-review/<int:analysis_id>/', score_review_v209.detail, name='dual-score-review-detail'),
    path('review-queue/', views.review_queue, name='dual-criteria-review-queue'),
    path('companies/<str:pk>/', views.private_company_framework, name='dual-criteria-company-internal'),
]
