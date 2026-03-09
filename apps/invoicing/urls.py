"""
Invoicing URLs
"""
from django.urls import path
from . import views

app_name = 'invoicing'

urlpatterns = [
    path('', views.invoice_list, name='invoice_list'),
    path('pending/', views.pending_invoices, name='pending_invoices'),
    path('create/', views.invoice_create, name='invoice_create'),
    path('<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('<int:pk>/edit/', views.invoice_edit, name='invoice_edit'),
    path('<int:pk>/print/', views.invoice_print, name='invoice_print'),
    path('<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('<int:pk>/payment/', views.add_payment, name='add_payment'),
    path('<int:pk>/send/', views.send_invoice, name='send_invoice'),
]
