"""
Accounts Models - CustomUser and Company
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings

from .models_tenant import Tenant, TenantManager, TenantAwareModel


class Company(TenantAwareModel):
    """Company model for customers, carriers, and vendors"""
    COMPANY_TYPE_CHOICES = [
        ('customer', 'Customer'),
        ('carrier', 'Carrier'),
        ('vendor', 'Vendor'),
    ]
    
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=255, blank=True)
    company_type = models.CharField(max_length=20, choices=COMPANY_TYPE_CHOICES, default='customer')
    tax_id = models.CharField(max_length=50, blank=True)
    
    # Address fields
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default='USA')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    
    # Contact fields
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)
    
    # Relationships & Extended Info
    services_provided = models.JSONField(default=list, blank=True, help_text="List of services provided")
    material_tags = models.ManyToManyField('inventory.Material', blank=True, related_name='associated_companies')
    company_tags = models.ManyToManyField('orders.Tag', blank=True, related_name='companies')
    
    # Financial fields
    payment_terms = models.IntegerField(default=30, help_text='Payment terms in days')
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Status
    CRM_STATUS_CHOICES = [
        ('active', 'Active'),
        ('cold', 'Cold'),
        ('dormant', 'Dormant'),
        ('lead', 'Lead'),
    ]
    crm_status = models.CharField(max_length=20, choices=CRM_STATUS_CHOICES, default='active')
    last_touch = models.DateField(null=True, blank=True)
    next_touch = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_companies')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Company'
        verbose_name_plural = 'Companies'
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
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
    is_contact_archived = models.BooleanField(default=False)
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
    

class SignupOTP(models.Model):
    """Model to store OTP for email verification during signup"""
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"OTP for {self.email} - {self.otp}"

class CompanyDocument(TenantAwareModel):
    """Company documents (certifications, contracts, etc.)"""
    DOCUMENT_TYPE_CHOICES = [
        ('certification', 'Certification'),
        ('contract', 'Contract'),
        ('insurance', 'Insurance'),
        ('tax', 'Tax Document'),
        ('other', 'Other'),
    ]
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='company_documents/%Y/%m/')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
    
class CompanyHistory(models.Model):
    """Activity log for company changes"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='history')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255) # e.g., "Added a new Contact"
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default='fas fa-info-circle')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Company History'
        verbose_name_plural = 'Company History'

    def __str__(self):
        return f"{self.company.name} - {self.action} at {self.created_at}"


class LoginAuditLog(models.Model):
    """Register for tracking every login attempt (pass or fail)"""
    STATUS_CHOICES = (
        ('success', 'Success'),
        ('failed', 'Failed'),
    )
    username = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Login Audit Log'
        verbose_name_plural = 'Login Audit Logs'
        
    def __str__(self):
        return f"{self.username} - {self.status} from {self.ip_address} at {self.timestamp}"


# --- Security Logic: Watch for Logins ---
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

def get_client_ip(request):
    """Helper to get user's real IP address from request"""
    if not request: return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

@receiver(user_logged_in)
def log_successful_login(sender, request, user, **kwargs):
    """Fires when someone logs in successfully"""
    ip = get_client_ip(request)
    ua = request.META.get('HTTP_USER_AGENT', '')[:250] if request else ''
    LoginAuditLog.objects.create(
        username=user.username,
        ip_address=ip,
        user_agent=ua,
        status='success'
    )

@receiver(user_login_failed)
def log_failed_login(sender, credentials, request, **kwargs):
    """Fires when a login attempt fails (wrong password etc)"""
    ip = get_client_ip(request)
    ua = request.META.get('HTTP_USER_AGENT', '')[:250] if request else ''
    LoginAuditLog.objects.create(
        username=credentials.get('username', getattr(credentials, 'email', 'Unknown')),
        ip_address=ip,
        user_agent=ua,
        status='failed'
    )
