"""
Customer Portal URLs
"""
from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    path('', views.customer_dashboard, name='dashboard'),
    path('shipments/', views.customer_shipments, name='shipments'),
    path('shipments/<int:pk>/', views.customer_shipment_detail, name='shipment_detail'),
    path('invoices/', views.customer_invoices, name='invoices'),
    path('invoices/<int:pk>/', views.customer_invoice_detail, name='invoice_detail'),
    path('track/<str:tracking_number>/', views.customer_tracking, name='tracking'),
    path('quote/request/', views.request_quote, name='request_quote'),
    path('inventory/', views.customer_inventory, name='inventory'),
    path('orders/create/', views.create_order, name='create_order'),
]
