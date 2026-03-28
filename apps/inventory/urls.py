"""
Inventory URLs
"""
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_item_list, name='item_list'),
    path('dashboard/', views.inventory_dashboard, name='dashboard'),
    path('warehouses/', views.warehouse_list, name='warehouse_list'),
    path('warehouses/create/', views.warehouse_create, name='warehouse_create'),
    path('warehouses/ajax-create/', views.ajax_warehouse_create, name='ajax_warehouse_create'),
    path('materials/ajax-create/', views.create_material_ajax, name='create_material_ajax'),
    path('warehouses/<int:pk>/', views.warehouse_detail, name='warehouse_detail'),
    path('warehouses/<int:pk>/edit/', views.warehouse_edit, name='warehouse_edit'),
    path('warehouses/<int:pk>/add-item/', views.inventory_item_add, name='inventory_item_add'),
    # Keep item_list here too for backward compatibility if needed, but point to same view
    # Actually, removing redundant path is cleaner.
    path('items/add/', views.inventory_item_add_general, name='inventory_item_add_general'),
    path('items/<int:pk>/', views.inventory_item_detail, name='item_detail'),
    path('items/<int:pk>/edit/', views.inventory_item_edit, name='inventory_item_edit'),
    path('items/<int:pk>/delete/', views.inventory_item_delete, name='inventory_item_delete'),
]
