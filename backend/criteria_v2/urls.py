from django.urls import path
from . import views

urlpatterns = [
    path('review-queue/', views.review_queue, name='dual-criteria-review-queue'),
    path('companies/<str:pk>/', views.private_company_framework, name='dual-criteria-company-internal'),
]
