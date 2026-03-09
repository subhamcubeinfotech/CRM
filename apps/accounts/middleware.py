import threading
from django.core.exceptions import ImproperlyConfigured

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
            if request.user.is_authenticated and hasattr(request.user, 'tenant') and request.user.tenant:
                set_current_tenant(request.user.tenant)
            else:
                set_current_tenant(None)
            
            response = self.get_response(request)
            return response
        finally:
            set_current_tenant(None)
