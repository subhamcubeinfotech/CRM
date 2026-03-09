"""
Inventory URLs
"""
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_dashboard, name='dashboard'),
    path('warehouses/', views.warehouse_list, name='warehouse_list'),
    path('warehouses/<int:pk>/', views.warehouse_detail, name='warehouse_detail'),
    path('items/', views.inventory_item_list, name='item_list'),
    path('items/<int:pk>/', views.inventory_item_detail, name='item_detail'),
]
