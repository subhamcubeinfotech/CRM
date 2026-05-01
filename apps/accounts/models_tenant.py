from django.db import models
from .middleware import get_current_tenant

class Tenant(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name

    @property
    def display_name(self):
        """Returns the tenant name without the word 'Tenant'."""
        return self.name.replace('Tenant', '').replace('tenant', '').strip()

    @property
    def platform_logo(self):
        """Always returns the system's first tenant's logo (Platform branding)."""
        try:
            # Get the very first tenant (the admin/platform owner)
            first_tenant = self.__class__.objects.order_by('id').first()
            if first_tenant and first_tenant.logo:
                return first_tenant.logo
        except:
            pass
        return self.logo

class TenantManager(models.Manager):
    def get_queryset(self):
        tenant = get_current_tenant()
        queryset = super().get_queryset()
        if tenant:
            return queryset.filter(tenant=tenant)
        return queryset

class TenantAwareModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="%(app_label)s_%(class)s_related", null=True, blank=True)
    
    objects = TenantManager()
    plain_objects = models.Manager()

    def save(self, *args, **kwargs):
        if not self.tenant:
            self.tenant = get_current_tenant()
        super().save(*args, **kwargs)

    class Meta:
        abstract = True
