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
    pickup_email = models.EmailField(max_length=254, blank=True)
    pickup_contact_phone = models.CharField(max_length=50, blank=True)
    pickup_number = models.CharField(max_length=50, blank=True)
    pickup_appointment_type = models.CharField(max_length=20, choices=APPOINTMENT_CHOICES, default='fcfs')
    
    # Delivery details
    destination_location = models.ForeignKey('inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_shipments')
    delivery_contact = models.CharField(max_length=255, blank=True)
    delivery_email = models.EmailField(max_length=254, blank=True)
    delivery_contact_phone = models.CharField(max_length=50, blank=True)
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
    total_weight = models.DecimalField(max_digits=20, decimal_places=2, default=0, help_text='Weight in kg')
    total_volume = models.DecimalField(max_digits=20, decimal_places=4, default=0, help_text='Volume in cubic meters')
    number_of_pieces = models.IntegerField(default=1)
    commodity_description = models.TextField(blank=True)
    
    # Special requirements
    is_hazmat = models.BooleanField(default=False, verbose_name='Hazardous Materials')
    is_temperature_controlled = models.BooleanField(default=False)
    requires_insurance = models.BooleanField(default=False)
    
    # Financial
    quoted_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    cost = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    
    # Notes
    special_instructions = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    
    # Commercial details
    shipping_terms = models.ForeignKey('orders.ShippingTerm', on_delete=models.SET_NULL, null=True, blank=True, related_name='shipments')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='represented_shipments')
    tags = models.ManyToManyField('orders.Tag', blank=True, related_name='shipments')
    
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

    def update_financials(self):
        """Calculate and sync total revenue and cost from shipment items"""
        total_revenue = 0
        total_cost = 0
        for item in self.items.all():
            weight = float(item.weight or 0)
            total_revenue += float(item.sell_price or 0) * weight
            total_cost += float(item.buy_price or 0) * weight
        
        self.revenue = total_revenue
        self.cost = total_cost
        self.save(update_fields=['revenue', 'cost', 'updated_at'])
    
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
    
    def sync_from_order(self, force=False):
        """Sync addresses and coordinates from linked Order and Companies"""
        if not self.order:
            return
        
        # 1. Pickup / Origin
        supplier = self.order.supplier
        pickup_loc = self.pickup_location or self.order.source_location
        
        # If origin_address is empty or contains "Bangalore" or force=True
        is_stale_origin = not self.origin_address or "Bangalore" in self.origin_address
        if is_stale_origin or force:
            if pickup_loc:
                self.origin_address = pickup_loc.address
                self.origin_city = pickup_loc.city
                self.origin_state = pickup_loc.state
                self.origin_postal_code = pickup_loc.postal_code
                self.origin_country = pickup_loc.country
            elif supplier:
                self.origin_address = supplier.address_line1
                self.origin_city = supplier.city
                self.origin_state = supplier.state
                self.origin_postal_code = supplier.postal_code
                self.origin_country = supplier.country
                # Also sync coordinates if they are available
                if supplier.latitude: self.origin_latitude = supplier.latitude
                if supplier.longitude: self.origin_longitude = supplier.longitude

        # 2. Destination
        receiver = self.order.receiver
        dest_loc = self.destination_location or self.order.destination_location
        
        is_stale_dest = not self.destination_address or "Bangalore" in self.destination_address
        if is_stale_dest or force:
            if dest_loc:
                self.destination_address = dest_loc.address
                self.destination_city = dest_loc.city
                self.destination_state = dest_loc.state
                self.destination_postal_code = dest_loc.postal_code
                self.destination_country = dest_loc.country
            elif receiver:
                self.destination_address = receiver.address_line1
                self.destination_city = receiver.city
                self.destination_state = receiver.state
                self.destination_postal_code = receiver.postal_code
                self.destination_country = receiver.country
                # Also sync coordinates if they are available
                if receiver.latitude: self.destination_latitude = receiver.latitude
                if receiver.longitude: self.destination_longitude = receiver.longitude

    def save(self, *args, **kwargs):
        # Auto-sync addresses from order if they are stale/placeholders
        self.sync_from_order()

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
    weight = models.DecimalField(max_digits=20, decimal_places=2, default=0, help_text='Weight in kg')
    
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


class ShipmentItem(models.Model):
    """Line items for a specific shipment"""
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='items')
    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='shipment_items')
    material_name = models.CharField(max_length=255)
    
    # Quantity/Weight
    weight = models.DecimalField(max_digits=20, decimal_places=2)
    weight_unit = models.CharField(max_length=10, default='lbs')
    gross_weight = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    gross_weight_unit = models.CharField(max_length=10, default='lbs', blank=True)
    tare_weight = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    tare_weight_unit = models.CharField(max_length=10, default='lbs', blank=True)
    packaging = models.CharField(max_length=100, blank=True)
    is_palletized = models.BooleanField(default=False)
    pieces = models.IntegerField(default=1, null=True, blank=True)
    
    # Financial
    buy_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    sell_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    price_unit = models.CharField(max_length=20, default='per lbs')
    
    class Meta:
        ordering = ['id']
        
    def __str__(self):
        return f"{self.material_name} ({self.weight} {self.weight_unit})"


class ShipmentCommission(models.Model):
    COMMISSION_TYPE_CHOICES = [
        ('fixed', 'Fixed'),
        ('gross_profit_pct', '% Gross Profit'),
        ('material_cost_pct', '% Material Cost'),
        ('material_sale_pct', '% Material Sale'),
    ]

    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='commissions')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    commission_type = models.CharField(max_length=30, choices=COMMISSION_TYPE_CHOICES, default='fixed')
    percentage = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    paid_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        rep = getattr(self.representative, 'username', None) or 'Unknown'
        return f"{self.shipment.shipment_number} - {rep} - {self.amount}"


class ShipmentHistory(models.Model):
    """Detailed audit log for shipment changes"""
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='history')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255) # e.g., "Changed Pickup Contact to राघव त्रेहन"
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default='fas fa-info-circle')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Shipment History'
        verbose_name_plural = 'Shipment History'

    def __str__(self):
        return f"{self.shipment.shipment_number} - {self.action} at {self.created_at}"


class ShipmentComment(models.Model):
    """Real-time conversation comments for a shipment"""
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shipment_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Shipment Comment'
        verbose_name_plural = 'Shipment Comments'

    def __str__(self):
        return f"Comment by {self.user.username} on {self.shipment.shipment_number}"
