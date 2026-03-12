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
    path('<str:pk>/', views.invoice_detail, name='invoice_detail'),  # Changed from int to str
    path('<str:pk>/edit/', views.invoice_edit, name='invoice_edit'),  # Changed from int to str
    path('<str:pk>/print/', views.invoice_print, name='invoice_print'),  # Changed from int to str
    path('<str:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),  # Changed from int to str
    path('<str:pk>/payment/', views.add_payment, name='add_payment'),  # Changed from int to str
    path('<str:pk>/send/', views.send_invoice, name='send_invoice'),  # Changed from int to str
]
