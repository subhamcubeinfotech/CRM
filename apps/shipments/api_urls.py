"""
API URLs for Shipments
"""
from django.urls import path
from . import api_views

urlpatterns = [
    path('shipments/', api_views.shipment_list_api, name='api_shipment_list'),
    path('shipments/<int:pk>/', api_views.shipment_detail_api, name='api_shipment_detail'),
    path('shipments/<int:pk>/tracking/', api_views.shipment_tracking_api, name='api_shipment_tracking'),
    path('calendar-events/', api_views.shipment_calendar_events, name='api_shipment_calendar_events'),
]
