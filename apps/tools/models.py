"""
Tools Models - Rate quotes and calculators
"""
from django.db import models


from apps.accounts.models import TenantAwareModel


class RateQuote(TenantAwareModel):
    """Rate quote model for freight rate comparison"""
    SHIPMENT_TYPE_CHOICES = [
        ('ftl', 'Full Truckload (FTL)'),
        ('ltl', 'Less Than Truckload (LTL)'),
        ('partial', 'Partial Truckload'),
    ]
    
    SERVICE_LEVEL_CHOICES = [
        ('economy', 'Economy'),
        ('standard', 'Standard'),
        ('expedited', 'Expedited'),
    ]
    
    # Quote details
    origin = models.CharField(max_length=200)
    destination = models.CharField(max_length=200)
    origin_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    origin_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Shipment details
    weight = models.DecimalField(max_digits=10, decimal_places=2, help_text='Weight in lbs')
    dimensions = models.CharField(max_length=100, blank=True, help_text='L x W x H in inches')
    shipment_type = models.CharField(max_length=20, choices=SHIPMENT_TYPE_CHOICES, default='ltl')
    service_level = models.CharField(max_length=20, choices=SERVICE_LEVEL_CHOICES, default='standard')
    
    # Carrier details
    carrier_name = models.CharField(max_length=100)
    carrier_logo = models.CharField(max_length=100, blank=True)
    
    # Pricing
    base_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fuel_surcharge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    additional_fees = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    insurance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Transit
    transit_days_min = models.IntegerField(default=1)
    transit_days_max = models.IntegerField(default=5)
    
    # Validity
    quoted_date = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateTimeField()
    
    # Status
    is_best_rate = models.BooleanField(default=False)
    is_selected = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-quoted_date', 'total_cost']
    
    def __str__(self):
        return f"{self.carrier_name} - {self.origin} to {self.destination} - ${self.total_cost}"
    
    @property
    def transit_time_display(self):
        """Return transit time as string"""
        if self.transit_days_min == self.transit_days_max:
            return f"{self.transit_days_min} day{'s' if self.transit_days_min > 1 else ''}"
        return f"{self.transit_days_min}-{self.transit_days_max} days"
