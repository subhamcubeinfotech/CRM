"""
Shipments URLs
"""
from django.urls import path
from . import views

app_name = 'shipments'

urlpatterns = [
    # Shipment CRUD
    path('', views.shipment_list, name='shipment_list'),
    path('create/', views.shipment_create, name='shipment_create'),
    path('<int:pk>/', views.shipment_detail, name='shipment_detail'),
    path('<int:pk>/edit/', views.shipment_edit, name='shipment_edit'),
    path('<int:pk>/delete/', views.shipment_delete, name='shipment_delete'),

    # Documents
    path('<int:pk>/document/upload/', views.document_upload, name='document_upload'),
    path('document/<int:doc_pk>/download/', views.document_download, name='document_download'),
    path('document/<int:doc_pk>/delete/', views.document_delete, name='document_delete'),

    # Document Generation
    path('<int:pk>/shipping-confirmation/', views.generate_shipping_confirmation, name='generate_shipping_confirmation'),
    path('<int:pk>/shipping-confirmation/pdf/', views.generate_shipping_confirmation_pdf, name='generate_shipping_confirmation_pdf'),
    path('<int:pk>/packing-list/', views.generate_packing_list, name='generate_packing_list'),
    path('<int:pk>/bol/', views.generate_bol, name='generate_bol'),
    path('<int:pk>/bol/pdf/', views.generate_bol_pdf, name='generate_bol_pdf'),
    path('<int:pk>/invoice/create/', views.create_invoice, name='create_invoice'),

    # Status update
    path('<int:pk>/update-status/', views.update_status, name='update_status'),

    # Tracking
    path('track/<str:tracking_number>/', views.public_tracking, name='public_tracking'),
]
