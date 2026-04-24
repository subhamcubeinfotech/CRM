from django.db import models
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
    
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='basic')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trialing')
    
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    
    start_date = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.tenant.name} - {self.get_plan_display()} ({self.status})"
