import threading
from django.core.exceptions import ImproperlyConfigured
from .utils import is_staff_user

_thread_local = threading.local()

def set_current_tenant(tenant):
    _thread_local.tenant = tenant

def get_current_tenant():
    return getattr(_thread_local, 'tenant', None)

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            # Superusers and staff users should see everything across all tenants
            is_internal = request.user.is_superuser or is_staff_user(request.user)
            if request.user.is_authenticated and not is_internal and hasattr(request.user, 'tenant') and request.user.tenant:
                set_current_tenant(request.user.tenant)
            else:
                set_current_tenant(None)
            
            response = self.get_response(request)
            return response
        finally:
            set_current_tenant(None)

class SubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            from .utils import is_staff_user
            if not is_staff_user(request.user) and hasattr(request.user, 'tenant') and request.user.tenant:
                # Check subscription status
                tenant = request.user.tenant
                subscription = getattr(tenant, 'subscription', None)
                
                # Allow paths
                from django.urls import resolve
                current_url_name = resolve(request.path_info).url_name
                
                allowed_url_names = [
                    'subscription_expired',
                    'billing_portal',
                    'signup_checkout',
                    'pricing',
                    'stripe_webhook',
                    'login',
                    'logout',
                    'password_reset',
                    'password_reset_done',
                    'password_reset_confirm',
                    'password_reset_complete',
                ]
                
                # Check if it's an admin path
                is_admin_path = request.path.startswith('/admin/')
                
                # Check if subscription is inactive and path is not allowed
                if (not subscription or not subscription.is_active) and current_url_name not in allowed_url_names and not is_admin_path:
                    from django.shortcuts import redirect
                    return redirect('accounts:subscription_expired')
                    
        return self.get_response(request)
