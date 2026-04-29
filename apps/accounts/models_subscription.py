from django.db import models
from django.utils import timezone
from .models_tenant import Tenant

class Subscription(models.Model):
    PLAN_CHOICES = [
        ('starter', 'Starter'),
        ('professional', 'Professional'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('trialing', 'Trialing'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
    ]
    
    # Plan limits: None means unlimited
    PLAN_LIMITS = {
        'starter': {
            'max_users': 1,
            'max_shipments_per_month': 100,
            'has_api_access': False,
            'has_ocean_tracking': False,
        },
        'professional': {
            'max_users': 3,
            'max_shipments_per_month': None,  # Unlimited
            'has_api_access': True,
            'has_ocean_tracking': True,
        },
    }
    
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='starter')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trialing')
    
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    
    start_date = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    def get_limits(self):
        """Returns the limits dict for the current plan."""
        return self.PLAN_LIMITS.get(self.plan, self.PLAN_LIMITS['starter'])
    
    def can_add_user(self):
        """Check if the tenant can add more users (active + pending invites)."""
        from django.contrib.auth import get_user_model
        from .models import TeamInvitation
        User = get_user_model()
        limits = self.get_limits()
        max_users = limits['max_users']
        if max_users is None:
            return True  # Unlimited
        # Exclude the Tenant Admin from the user limit count
        active_count = User.objects.filter(tenant=self.tenant, is_active=True).exclude(role='tenant_admin').count()
        pending_count = TeamInvitation.objects.filter(tenant=self.tenant, is_accepted=False).count()
        return (active_count + pending_count) < max_users
    
    def can_create_shipment(self):
        """Check if the tenant can create more shipments this month."""
        from apps.shipments.models import Shipment
        limits = self.get_limits()
        max_shipments = limits['max_shipments_per_month']
        if max_shipments is None:
            return True  # Unlimited
        now = timezone.now()
        monthly_count = Shipment.objects.filter(
            tenant=self.tenant,
            created_at__year=now.year,
            created_at__month=now.month
        ).count()
        return monthly_count < max_shipments
    
    def get_usage_info(self):
        """Returns current usage vs limits for display."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        limits = self.get_limits()
        
        user_count = User.objects.filter(tenant=self.tenant, is_active=True).count()
        max_users = limits['max_users']
        
        return {
            'user_count': user_count,
            'max_users': max_users if max_users else '∞',
            'max_shipments': limits['max_shipments_per_month'] if limits['max_shipments_per_month'] else '∞',
            'has_api_access': self.has_api_access(),
            'has_ocean_tracking': self.has_ocean_tracking(),
        }

    def has_api_access(self):
        """Check if the current plan allows API access."""
        return self.get_limits().get('has_api_access', False)

    def has_ocean_tracking(self):
        """Check if the current plan allows advanced ocean tracking."""
        return self.get_limits().get('has_ocean_tracking', False)
    
    def __str__(self):
        return f"{self.tenant.name} - {self.get_plan_display()} ({self.status})"
