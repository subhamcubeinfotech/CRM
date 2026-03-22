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
        ('pending', 'Pending'),
        ('dispatched', 'Dispatched'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('approved', 'Approved'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
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

    APPOINTMENT_CHOICES = [
        ('fcfs', 'FCFS'),
        ('required', 'Required'),
    ]

    # Pickup details
    pickup_location = models.ForeignKey('inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='pickup_shipments')
    pickup_contact = models.CharField(max_length=255, blank=True)
    pickup_number = models.CharField(max_length=50, blank=True)
    pickup_appointment_type = models.CharField(max_length=20, choices=APPOINTMENT_CHOICES, default='fcfs')
    
    # Delivery details
    destination_location = models.ForeignKey('inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_shipments')
    delivery_contact = models.CharField(max_length=255, blank=True)
    delivery_number = models.CharField(max_length=50, blank=True)
    delivery_appointment_type = models.CharField(max_length=20, choices=APPOINTMENT_CHOICES, default='fcfs')

    
    # Current location (for tracking)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_location_text = models.CharField(max_length=255, blank=True)
    last_location_updated_at = models.DateTimeField(null=True, blank=True)
    tracking_active = models.BooleanField(default=False)
    vehicle_number = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=150, blank=True)
    driver_phone = models.CharField(max_length=20, blank=True)
    
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
    def ordered_statuses(self):
        """Return the list of statuses in progress order for the UI"""
        return ['pending', 'dispatched', 'in_transit', 'delivered', 'approved', 'invoiced', 'paid']

    @property
    def status_index(self):
        """Return the index of the current status in the progress order"""
        status_order = self.ordered_statuses
        if self.status in status_order:
            return status_order.index(self.status)
        return -1

    @property
    def progress_percentage(self):
        """Calculate shipment progress percentage"""
        if self.status == 'rejected':
            return 100
        idx = self.status_index
        if idx >= 0:
            return int((idx / (len(self.ordered_statuses) - 1)) * 100)
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
    def current_location_display(self):
        """Human-friendly current location for the tracking UI."""
        if self.last_location_text:
            return self.last_location_text
        if self.current_latitude and self.current_longitude:
            return f"{self.current_latitude}, {self.current_longitude}"
        return "Awaiting live update"
    
    @property
    def route_display(self):
        """Return route as string"""
        return f"{self.origin_full} → {self.destination_full}"
    
    def save(self, *args, **kwargs):
        # Auto-generate shipment number if not set with proper transaction handling
        if not self.shipment_number:
            from django.db import transaction
            import time
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with transaction.atomic():
                        # Generate the number inside the transaction
                        self.shipment_number = self._generate_shipment_number_internal()
                        # Call the parent save within the same transaction
                        super().save(*args, **kwargs)
                        return  # Success, exit the function
                        
                except Exception as e:
                    if attempt == max_retries - 1:
                        # If all retries fail, use timestamp as fallback and try once more
                        timestamp = int(time.time())
                        year = datetime.now().year
                        self.shipment_number = f"SHP-{year}-{timestamp % 99999:05d}"
                        super().save(*args, **kwargs)
                        return
                    time.sleep(0.1)  # Small delay before retry
        else:
            # If shipment number is already set, just save normally
            super().save(*args, **kwargs)
    
    def _generate_shipment_number_internal(self):
        """Internal method to generate shipment number - called within transaction"""
        year = datetime.now().year
        # Use select_for_update to prevent race conditions
        last_shipment = Shipment.objects.filter(
            shipment_number__startswith=f'SHP-{year}'
        ).select_for_update().order_by('-shipment_number').first()
        
        if last_shipment:
            try:
                last_num = int(last_shipment.shipment_number.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        
        new_shipment_number = f"SHP-{year}-{new_num:05d}"
        
        # Double-check that this number doesn't exist
        if Shipment.objects.filter(shipment_number=new_shipment_number).exists():
            # If it exists, try again with a higher number
            new_num += 1
            new_shipment_number = f"SHP-{year}-{new_num:05d}"
        
        return new_shipment_number


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
