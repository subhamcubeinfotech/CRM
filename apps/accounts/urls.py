"""
Accounts URLs
"""
from django.urls import path
from . import views, views_team, views_profile, views_auth

app_name = 'accounts'

urlpatterns = [
    path('', views.company_list, name='company_list'),
    path('', views.company_list, name='company_list'),
    path('customers/', views.customer_list, name='customer_list'),
    path('carriers/', views.carrier_list, name='carrier_list'),
    path('team/', views_team.team_list, name='team_list'),
    path('create/', views.company_create, name='company_create'),
    path('<int:pk>/', views.company_detail, name='company_detail'),
    path('<int:pk>/edit/', views.company_edit, name='company_edit'),
    path('<int:pk>/delete/', views.company_delete, name='company_delete'),
    path('<int:pk>/document/upload/', views.company_document_upload, name='company_document_upload'),
    path('document/<int:doc_pk>/delete/', views.company_document_delete, name='company_document_delete'),
    
    # Profile & Settings
    path('profile/', views_profile.profile_view, name='profile'),
    path('settings/', views_profile.settings_view, name='settings'),
    
    # AJAX OTP Endpoints
    path('ajax/send-otp/', views_auth.ajax_send_otp, name='ajax_send_otp'),
    path('ajax/verify-otp/', views_auth.ajax_verify_otp, name='ajax_verify_otp'),
    path('ajax/edit-contact/', views.ajax_edit_contact, name='ajax_edit_contact'),
    path('ajax/archive-contact/', views.ajax_archive_contact, name='ajax_archive_contact'),
    path('ajax/add-contact/', views.ajax_add_contact, name='ajax_add_contact'),
    path('ajax/help-ticket/', views.ajax_help_ticket, name='ajax_help_ticket'),
    path('<int:pk>/ajax/associate-material/', views.ajax_associate_material, name='ajax_associate_material'),
    path('<int:pk>/ajax/update-about/', views.ajax_update_company_about, name='ajax_update_company_about'),
]
