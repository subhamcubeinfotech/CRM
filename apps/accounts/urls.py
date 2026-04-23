"""
Accounts URLs
"""
from django.urls import path
from . import views, views_team, views_profile, views_auth, views_stripe

app_name = 'accounts'

urlpatterns = [
    # Stripe Signup Flow
    path('signup/checkout/<int:tenant_id>/', views_stripe.CreateCheckoutSessionView.as_view(), name='signup_checkout'),
    path('signup/success/', views_stripe.SignupSuccessView.as_view(), name='signup_success'),
    path('signup/cancel/', views_stripe.SignupCancelView.as_view(), name='signup_cancel'),
    path('webhook/stripe/', views_stripe.StripeWebhookView.as_view(), name='stripe_webhook'),
    path('', views.company_list, name='company_list'),
    path('', views.company_list, name='company_list'),
    path('map-dashboard/', views.map_dashboard, name='map_dashboard'),
    path('map-dashboard/data/', views.map_dashboard_data, name='map_dashboard_data'),
    path('customers/', views.customer_list, name='customer_list'),
    path('carriers/', views.carrier_list, name='carrier_list'),
    path('team/', views_team.team_list, name='team_list'),
    path('team/invite/', views_team.invite_team_member, name='team_invite'),
    path('team/accept/<uuid:token>/', views_team.accept_invitation, name='accept_invitation'),
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
    path('ajax/unarchive-contact/', views.ajax_unarchive_contact, name='ajax_unarchive_contact'),
    path('ajax/add-contact/', views.ajax_add_contact, name='ajax_add_contact'),
    path('ajax/help-ticket/', views.ajax_help_ticket, name='ajax_help_ticket'),
    path('<int:pk>/ajax/associate-material/', views.ajax_associate_material, name='ajax_associate_material'),
    path('<int:pk>/ajax/update-about/', views.ajax_update_company_about, name='ajax_update_company_about'),
    path('<int:pk>/ajax/update-logo/', views.ajax_update_company_logo, name='ajax_update_company_logo'),
    path('<int:pk>/ajax/remove-logo/', views.ajax_remove_company_logo, name='ajax_remove_company_logo'),
]
