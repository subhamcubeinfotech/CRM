from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.OrderListView.as_view(), name='order_list'),
    path('<int:pk>/', views.OrderDetailView.as_view(), name='order_detail'),
    path('<int:pk>/update-status/', views.order_update_status, name='order_update_status'),
    path('<int:pk>/edit/', views.order_edit, name='order_edit'),
    path('create/', views.order_create, name='order_create'),
    path('<int:pk>/purchase-order/', views.order_purchase_order_pdf, name='order_purchase_order_pdf'),
    path('<int:pk>/add-item/', views.order_add_item, name='order_add_item'),
]
