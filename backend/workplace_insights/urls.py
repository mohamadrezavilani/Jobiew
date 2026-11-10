from django.contrib import admin
from django.urls import path, include
from criteria_v2 import views as dual_criteria_views
from criteria_v2 import legacy_bridge as dual_legacy_bridge
from companies import views as company_views
from companies import homepage_preview_v219
from companies.research_five_criteria_v7 import staff_five_criteria_preview
from companies.research_five_criteria_compare_v12 import staff_five_criteria_compare
from companies.research_five_criteria_analytics_v13 import staff_five_criteria_analytics
from locations.map_asset_proxy_v39 import map_asset
from locations.admin_reverse_geocode_v45 import reverse_address

urlpatterns=[
    path('admin/',admin.site.urls),
    path('internal/homepage-preview/',homepage_preview_v219.preview,name='homepage-preview-v219'),
    path('internal/criteria/', include('criteria_v2.urls')),  # jobiew_dual_framework_v200
    path('admin-map-assets/<path:asset_path>', map_asset, name='admin-map-assets'),
    path('admin-location-reverse/', reverse_address, name='admin-location-reverse-v45'),
    path('',company_views.index,name='company-index'),
    path('companies/<str:pk>/',company_views.detail,name='company-detail'),
    path('internal/companies/<str:pk>/five-criteria/', dual_legacy_bridge.historical_preview, name='company-five-criteria-private-preview'),
    path('internal/companies/compare-five-criteria/', dual_legacy_bridge.historical_compare, name='company-five-criteria-private-compare'),
    path('internal/companies/analytics-five-criteria/', dual_legacy_bridge.historical_analytics, name='company-five-criteria-private-analytics'),
    path('map/', company_views.company_map, name='company-map'),
    path('api/locations.geojson',company_views.approved_geojson,name='verified-company-locations'),
]
