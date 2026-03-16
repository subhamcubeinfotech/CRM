from django.urls import path
from . import views

app_name = 'materials'

urlpatterns = [
    path('<int:pk>/', views.material_detail, name='material_detail'),
    path('lookup/', views.material_detail, name='material_lookup'),
]
