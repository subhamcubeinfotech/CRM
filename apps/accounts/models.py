"""
Accounts Models - CustomUser and Company
"""
from django.contrib.auth.models import AbstractUser
from django.db import models

from .models_tenant import Tenant, TenantManager, TenantAwareModel


class Company(TenantAwareModel):
    """Company model for customers, carriers, and vendors"""
    COMPANY_TYPE_CHOICES = [
        ('customer', 'Customer'),
        ('carrier', 'Carrier'),
        ('vendor', 'Vendor'),
    ]
    
    name = models.CharField(max_length=200)
    company_type = models.CharField(max_length=20, choices=COMPANY_TYPE_CHOICES, default='customer')
    tax_id = models.CharField(max_length=50, blank=True)
    
    # Address fields
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default='USA')
    
    # Contact fields
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    
    # Financial fields
    payment_terms = models.IntegerField(default=30, help_text='Payment terms in days')
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Company'
        verbose_name_plural = 'Companies'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_company_type_display()})"
    
    @property
    def full_address(self):
        """Return full address as a single string"""
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.append(f"{self.city}, {self.state} {self.postal_code}")
        parts.append(self.country)
        return ', '.join(filter(None, parts))


class CustomUser(AbstractUser):
    """Custom user model with role-based access"""
    ROLE_CHOICES = [
        ('admin', 'Administrator'),
        ('customer', 'Customer'),
        ('driver', 'Driver'),
        ('warehouse', 'Warehouse Staff'),
        ('sales', 'Sales'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name='users')
    phone = models.CharField(max_length=20, blank=True)
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['username']
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    @property
    def is_customer(self):
        return self.role == 'customer'
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    @property
    def is_driver(self):
        return self.role == 'driver'
    
    @property
    def is_warehouse_staff(self):
        return self.role == 'warehouse'
    


class SystemSetting(models.Model):
    """Generic settings model to allow configuration via UI (Admin)"""
    key = models.CharField(max_length=100, unique=True, help_text="Unique key for the setting (e.g. 'wholesale_recipient')")
    value = models.TextField(help_text="The value of the setting")
    description = models.CharField(max_length=255, blank=True, help_text="What this setting controls")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_val(cls, key, default=None):
        """Helper to get setting value by key"""
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default
