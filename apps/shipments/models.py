"""
Shipments Models - Core shipment management
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import datetime


from apps.accounts.models import TenantAwareModel

class Shipment(TenantAwareModel):
    """Core shipment model"""
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='shipments')
    SHIPMENT_TYPE_CHOICES = [
        ('ocean', 'Ocean Freight'),
        ('air', 'Air Freight'),
        ('road', 'Road Freight'),
        ('rail', 'Rail Freight'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('booked', 'Booked'),
        ('picked_up', 'Picked Up'),
        ('in_transit', 'In Transit'),
        ('customs', 'In Customs'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Identification
    shipment_number = models.CharField(max_length=50, unique=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    booking_number = models.CharField(max_length=100, blank=True)
    
    # Related parties
    customer = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='shipments_as_customer', limit_choices_to={'company_type': 'customer'})
    carrier = models.ForeignKey('accounts.Company', on_delete=models.SET_NULL, null=True, blank=True, related_name='shipments_as_carrier', limit_choices_to={'company_type': 'carrier'})
    shipper = models.ForeignKey('accounts.Company', on_delete=models.SET_NULL, null=True, blank=True, related_name='shipments_as_shipper')
    consignee = models.ForeignKey('accounts.Company', on_delete=models.SET_NULL, null=True, blank=True, related_name='shipments_as_consignee')
    
    # Shipment details
    shipment_type = models.CharField(max_length=20, choices=SHIPMENT_TYPE_CHOICES, default='road')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Origin address
    origin_address = models.CharField(max_length=255, blank=True)
    origin_city = models.CharField(max_length=100, blank=True)
    origin_state = models.CharField(max_length=100, blank=True)
    origin_country = models.CharField(max_length=100, blank=True, default='USA')
    origin_postal_code = models.CharField(max_length=20, blank=True)
    origin_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    origin_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Destination address
    destination_address = models.CharField(max_length=255, blank=True)
    destination_city = models.CharField(max_length=100, blank=True)
    destination_state = models.CharField(max_length=100, blank=True)
    destination_country = models.CharField(max_length=100, blank=True, default='USA')
    destination_postal_code = models.CharField(max_length=20, blank=True)
    destination_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Current location (for tracking)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Schedule
    pickup_date = models.DateField(null=True, blank=True)
    estimated_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)
    
    # Cargo details
    total_weight = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Weight in kg')
    total_volume = models.DecimalField(max_digits=12, decimal_places=4, default=0, help_text='Volume in cubic meters')
    number_of_pieces = models.IntegerField(default=1)
    commodity_description = models.TextField(blank=True)
    
    # Special requirements
    is_hazmat = models.BooleanField(default=False, verbose_name='Hazardous Materials')
    is_temperature_controlled = models.BooleanField(default=False)
    requires_insurance = models.BooleanField(default=False)
    
    # Financial
    quoted_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Notes
    special_instructions = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_shipments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.shipment_number} - {self.customer.name}"
    
    @property
    def gross_profit(self):
        """Calculate gross profit"""
        return self.revenue - self.cost
    
    @property
    def profit_margin(self):
        """Calculate profit margin percentage"""
        if self.revenue > 0:
            return (self.gross_profit / self.revenue) * 100
        return 0
    
    @property
    def is_overdue(self):
        """Check if shipment is overdue"""
        if self.estimated_delivery_date and self.status != 'delivered':
            return self.estimated_delivery_date < timezone.now().date()
        return False
    
    @property
    def progress_percentage(self):
        """Calculate shipment progress percentage"""
        status_order = ['draft', 'booked', 'picked_up', 'in_transit', 'customs', 'out_for_delivery', 'delivered']
        if self.status in status_order:
            return int((status_order.index(self.status) / (len(status_order) - 1)) * 100)
        return 0
    
    @property
    def origin_full(self):
        """Return origin as full string"""
        parts = [self.origin_city]
        if self.origin_state:
            parts.append(self.origin_state)
        parts.append(self.origin_country)
        return ', '.join(filter(None, parts))
    
    @property
    def destination_full(self):
        """Return destination as full string"""
        parts = [self.destination_city]
        if self.destination_state:
            parts.append(self.destination_state)
        parts.append(self.destination_country)
        return ', '.join(filter(None, parts))
    
    @property
    def route_display(self):
        """Return route as string"""
        return f"{self.origin_full} → {self.destination_full}"
    
    def save(self, *args, **kwargs):
        # Auto-generate shipment number if not set
        if not self.shipment_number:
            self.shipment_number = self.generate_shipment_number()
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_shipment_number():
        """Generate unique shipment number"""
        year = datetime.now().year
        last_shipment = Shipment.objects.filter(shipment_number__startswith=f'SHP-{year}').order_by('-shipment_number').first()
        if last_shipment:
            try:
                last_num = int(last_shipment.shipment_number.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        return f"SHP-{year}-{new_num:05d}"


class Container(models.Model):
    """Container model for ocean/rail shipments"""
    SIZE_CHOICES = [
        ('20ft', '20 ft Standard'),
        ('40ft', '40 ft Standard'),
        ('40hc', '40 ft High Cube'),
        ('45ft', '45 ft High Cube'),
    ]
    
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='containers')
    container_number = models.CharField(max_length=50)
    seal_number = models.CharField(max_length=50, blank=True)
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, default='40ft')
    weight = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Weight in kg')
    
    class Meta:
        ordering = ['container_number']
    
    def __str__(self):
        return f"{self.container_number} ({self.get_size_display()})"


class ShipmentMilestone(models.Model):
    """Shipment milestone tracking"""
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='milestones')
    status = models.CharField(max_length=50)
    location = models.CharField(max_length=200, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Shipment Milestone'
        verbose_name_plural = 'Shipment Milestones'
    
    def __str__(self):
        return f"{self.shipment.shipment_number} - {self.status} at {self.timestamp}"


class Document(models.Model):
    """Shipment documents"""
    DOCUMENT_TYPE_CHOICES = [
        ('bol', 'Bill of Lading'),
        ('commercial_invoice', 'Commercial Invoice'),
        ('packing_list', 'Packing List'),
        ('customs', 'Customs Document'),
        ('certificate', 'Certificate'),
        ('insurance', 'Insurance Document'),
        ('pod', 'Proof of Delivery'),
        ('other', 'Other'),
    ]
    
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='shipment_documents/%Y/%m/')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_document_type_display()})"
