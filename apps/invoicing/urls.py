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
    path('ajax/customer-shipments/<int:customer_id>/', views.get_customer_shipments, name='get_customer_shipments'),
    path('reports/aging/', views.aging_report, name='aging_report'),
    path('recurring/', views.recurring_invoice_list, name='recurring_invoice_list'),
    path('recurring/create/', views.recurring_invoice_create, name='recurring_invoice_create'),
    path('recurring/trigger/', views.trigger_recurring_generation, name='trigger_recurring_generation'),
    path('<str:pk>/', views.invoice_detail, name='invoice_detail'),  # Generic path last
    path('<str:pk>/edit/', views.invoice_edit, name='invoice_edit'),
    path('<str:pk>/print/', views.invoice_print, name='invoice_print'),
    path('<str:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('<str:pk>/payment/', views.add_payment, name='add_payment'),
    path('<str:pk>/send/', views.send_invoice, name='send_invoice'),
    path('<str:pk>/credit-memo/', views.add_credit_memo, name='add_credit_memo'),
    path('<str:pk>/status/', views.update_invoice_status, name='update_invoice_status'),
    path('portal/<str:token>/', views.public_invoice_detail, name='public_invoice_detail'),
]
