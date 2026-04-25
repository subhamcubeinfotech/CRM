"""AI Assistant URL Configuration"""
from django.urls import path
from . import views

app_name = 'ai_assistant'

urlpatterns = [
    # Feature A: Chat API
    path('chat/', views.chat_api, name='chat_api'),
    path('chat/history/', views.chat_history, name='chat_history'),
    path('chat/clear/', views.chat_clear, name='chat_clear'),
    
    # Feature B: Pending Inventory
    path('pending-inventory/', views.pending_inventory_list, name='pending_inventory'),
    path('pending-inventory/item/<int:item_id>/approve/', views.approve_pending_item, name='approve_item'),
    path('pending-inventory/item/<int:item_id>/reject/', views.reject_pending_item, name='reject_item'),
    path('pending-inventory/email/<int:email_id>/approve-all/', views.approve_all_items, name='approve_all'),
    path('pending-inventory/email/<int:email_id>/reject-all/', views.reject_all_items, name='reject_all'),
    
    # Feature C: Smart Matches
    path('smart-matches/', views.smart_matches_dashboard, name='smart_matches'),
    path('smart-matches/<int:match_id>/dismiss/', views.dismiss_match, name='dismiss_match'),
    path('smart-matches/<int:match_id>/notify/', views.notify_match_parties, name='notify_match_parties'),
    path('smart-matches/requirement/<int:requirement_id>/find/', views.find_match_for_requirement, name='find_match_for_requirement'),
    path('smart-matches/<int:match_id>/draft-quote/', views.draft_quote_for_match, name='draft_quote_for_match'),

    # Feature E: Additional AI Enhancements
    path('enhancements/', views.enhancements_dashboard, name='enhancements_dashboard'),
    path('enhancements/forecasts/refresh/', views.refresh_forecasts, name='refresh_forecasts'),
    path('enhancements/quote-drafts/<int:draft_id>/send/', views.send_quote_draft_view, name='send_quote_draft'),
    path('enhancements/ocr/upload/', views.document_vision_upload, name='document_vision_upload'),
]
