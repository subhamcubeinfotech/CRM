"""
Accounts URLs
"""
from django.urls import path
from . import views, views_team

app_name = 'accounts'

urlpatterns = [
    path('', views.company_list, name='company_list'),
    path('customers/', views.customer_list, name='customer_list'),
    path('carriers/', views.carrier_list, name='carrier_list'),
    path('team/', views_team.team_list, name='team_list'),
    path('create/', views.company_create, name='company_create'),
    path('<int:pk>/', views.company_detail, name='company_detail'),
]
