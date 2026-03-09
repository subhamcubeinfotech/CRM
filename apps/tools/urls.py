"""
Tools URLs
"""
from django.urls import path
from . import views

app_name = 'tools'

urlpatterns = [
    path('rate-comparison/', views.rate_comparison, name='rate_comparison'),
    path('rate-comparison/calculate/', views.calculate_rates, name='calculate_rates'),
    path('rate-comparison/quote/', views.generate_quote_pdf, name='generate_quote_pdf'),
]
