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
