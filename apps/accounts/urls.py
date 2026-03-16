"""
Accounts URLs
"""
from django.urls import path
from . import views, views_team, views_profile, views_auth

app_name = 'accounts'

urlpatterns = [
    path('', views.company_list, name='company_list'),
    path('customers/', views.customer_list, name='customer_list'),
    path('carriers/', views.carrier_list, name='carrier_list'),
    path('team/', views_team.team_list, name='team_list'),
    path('create/', views.company_create, name='company_create'),
    path('<int:pk>/', views.company_detail, name='company_detail'),
    path('<int:pk>/edit/', views.company_edit, name='company_edit'),
    path('<int:pk>/delete/', views.company_delete, name='company_delete'),
    path('<int:pk>/request-wholesale/', views.wholesale_request_view, name='wholesale_request'),
    
    # Profile & Settings
    path('profile/', views_profile.profile_view, name='profile'),
    path('settings/', views_profile.settings_view, name='settings'),
    path('wholesale-request/', views_auth.public_wholesale_request_view, name='public_wholesale_request'),
]
