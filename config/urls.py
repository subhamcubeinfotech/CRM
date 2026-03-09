"""
URL Configuration for Freight Platform
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from apps.accounts import views as account_views
from apps.shipments import views as shipment_views

# Custom error handlers
handler403 = 'django.views.defaults.permission_denied'
handler404 = 'django.views.defaults.page_not_found'

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Authentication
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', account_views.custom_logout, name='logout'),
    
    # Marketing & Public Site
    path('', include('apps.marketing.urls')),
    
    # Dashboard
    path('dashboard/', shipment_views.dashboard, name='dashboard'),
    
    # App URLs
    path('shipments/', include('apps.shipments.urls')),
    path('invoices/', include('apps.invoicing.urls', namespace='invoicing')),
    path('orders/', include('apps.orders.urls', namespace='orders')),
    path('inventory/', include('apps.inventory.urls', namespace='inventory')),
    path('companies/', include('apps.accounts.urls')),
    path('portal/', include('apps.customers.urls')),
    path('tools/', include('apps.tools.urls')),
    
    # API
    path('api/', include('apps.shipments.api_urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
