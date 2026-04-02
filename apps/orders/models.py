from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.accounts.models import TenantAwareModel

class Tag(TenantAwareModel):
    """Tag model for categorizing orders"""
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, default='secondary', help_text='Bootstrap color class (primary, success, danger, warning, info, secondary)')

    class Meta:
        ordering = ['name']
        unique_together = ('tenant', 'name')

    def __str__(self):
        return self.name


class ShippingTerm(TenantAwareModel):
    """Shipping term model - managed via Admin"""
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']
        unique_together = ('tenant', 'name')

    def __str__(self):
        return self.name


class PackagingType(models.Model):
    """Packaging type model - managed via Admin"""
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Order(TenantAwareModel):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Payment Pending'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
    ]

    WEIGHT_UNIT_CHOICES = [
        ('lbs', 'lbs'),
        ('kgs', 'kgs'),
        ('mt', 'MT'),
        ('st', 'ST'),
        ('pcs', 'pcs'),
    ]
    order_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    po_number = models.CharField(max_length=100, blank=True, verbose_name="Customer PO Number")
    so_number = models.CharField(max_length=100, blank=True, verbose_name="SO Number")
    
    # Parties
    supplier = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='orders_as_supplier')
    receiver = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='orders_as_receiver')
    
    # Locations
    source_location = models.ForeignKey('inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders_as_source')
    destination_location = models.ForeignKey('inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders_as_destination')
    
    # Logistics details
    shipping_terms = models.ForeignKey(ShippingTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    tags = models.ManyToManyField(Tag, blank=True, related_name='orders')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='represented_orders')
    
    # Weight tracking
    total_weight_target = models.DecimalField(max_digits=15, decimal_places=2, help_text="Target weight in the selected unit")
    total_weight_unit = models.CharField(max_length=10, choices=WEIGHT_UNIT_CHOICES, default='lbs')
    
    # Financial details
    freight_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Total estimated freight shipment cost")
    
    # Schedule
    expected_pickup_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_orders')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number} - {self.po_number}"

    def check_payment_status(self):
        """
        Check if the payment status should be updated to 'overdue' based on Net 30 terms.
        This is called during detail view and other key actions to keep stats accurate.
        """
        if self.payment_status in ['pending', 'partial']:
            days_since_creation = (timezone.now() - self.created_at).days
            if days_since_creation >= 30:
                self.payment_status = 'overdue'
                self.save(update_fields=['payment_status'])
                return True
        return False

    @property
    def shipped_weight(self):
        """Calculate total weight shipped across all associated shipments (converted to lbs)"""
        # Shipment.total_weight is stored in kg (canonical system unit for shipments)
        # Convert kg to lbs: kg * 2.20462
        from decimal import Decimal
        total_kg = sum(s.total_weight for s in self.shipments.all())
        return total_kg * Decimal('2.20462')

    @property
    def shipped_weight_in_unit(self):
        """Calculate total weight shipped across all associated shipments (converted to total_weight_unit)"""
        from decimal import Decimal
        lbs = self.shipped_weight
        unit = self.total_weight_unit.lower()
        if unit == 'lbs': return lbs
        if unit in ['kg', 'kgs']: return lbs / Decimal('2.20462')
        if unit == 'mt': return lbs / Decimal('2204.62')
        if unit == 'st': return lbs / Decimal('2000.0')
        return lbs

    @property
    def total_pieces(self):
        """Calculate total pieces from manifest items where unit is pcs"""
        return sum(item.weight for item in self.manifest_items.filter(weight_unit='pcs'))

    @property
    def total_manifest_weight(self):
        """Calculate total weight from manifest items where unit is not pcs (normalized to lbs)"""
        return sum(item.normalized_weight for item in self.manifest_items.exclude(weight_unit='pcs'))

    @property
    def total_manifest_weight_in_unit(self):
        """Calculate total weight from manifest items (converted to total_weight_unit)"""
        from decimal import Decimal
        lbs = self.total_manifest_weight
        unit = self.total_weight_unit.lower()
        if unit == 'lbs': return lbs
        if unit in ['kg', 'kgs']: return lbs / Decimal('2.20462')
        if unit == 'mt': return lbs / Decimal('2204.62')
        if unit == 'st': return lbs / Decimal('2000.0')
        return lbs

    @property
    def manifest_progress_percentage(self):
        """Calculate manifested weight progress percentage against target"""
        if self.total_weight_target > 0:
            return min(int((self.total_manifest_weight_in_unit / self.total_weight_target) * 100), 100)
        return 0

    @property
    def weight_progress_percentage(self):
        """Calculate shipped weight progress percentage against target"""
        if self.total_weight_target > 0:
            return min(int((self.shipped_weight_in_unit / self.total_weight_target) * 100), 100)
        return 0

    @property
    def total_revenue(self):
        """Calculate total revenue from manifest items"""
        return sum(item.total_sell_price for item in self.manifest_items.all())

    @property
    def total_cost(self):
        """Calculate total cost from manifest items"""
        return sum(item.total_buy_price for item in self.manifest_items.all())

    @property
    def gross_profit(self):
        """Calculate gross profit (Revenue - Cost - Freight Cost)"""
        return self.total_revenue - self.total_cost - self.freight_cost

    @property
    def live_status_info(self):
        """
        Returns a dict with 'status' and 'label' representing the most advanced 
        live status from associated shipments, or the order status if no shipments.
        """
        shipments = self.shipments.all()
        if not shipments.exists():
            return {
                'status': self.status,
                'label': self.get_status_display(),
                'source': 'order'
            }
        
        # Shipment status ranking (higher is more advanced)
        ranking = {
            'pending': 10,
            'dispatched': 20,
            'in_transit': 30,
            'delivered': 40,
            'approved': 50,
            'invoiced': 60,
            'paid': 70,
            'rejected': 0,
        }
        
        # Find shipment with highest rank
        best_shipment = None
        max_rank = -1
        best_shipment = None
        
        for s in shipments:
            rank = ranking.get(s.status, 0)
            if rank > max_rank:
                max_rank = rank
                best_shipment = s
        
        if best_shipment:
            return {
                'status': best_shipment.status,
                'label': best_shipment.get_status_display(),
                'source': 'shipment'
            }
        
        return {
            'status': self.status,
            'label': self.get_status_display(),
            'source': 'order'
        }

    @property
    def live_status(self):
        return self.live_status_info['label']

    @property
    def live_status_code(self):
        return self.live_status_info['status']

    @property
    def live_status_class(self):
        """Returns the appropriate Bootstrap color class for the live status badge"""
        code = self.live_status_code
        mapping = {
            'draft': 'secondary',
            'pending': 'warning',
            'confirmed': 'primary',
            'dispatched': 'info',
            'in_transit': 'primary',
            'delivered': 'success',
            'approved': 'info',
            'invoiced': 'warning',
            'paid': 'success',
            'closed': 'success',
            'rejected': 'danger',
            'cancelled': 'danger',
        }
        return mapping.get(code, 'secondary')

    @property
    def simple_status_label(self):
        """Returns 'Complete' for delivered/closed, 'Open' otherwise"""
        if self.status in ['delivered', 'closed']:
            return 'Complete'
        return 'Open'

    @property
    def simple_status_class(self):
        """Returns success for Complete, primary for Open"""
        if self.status in ['delivered', 'closed']:
            return 'success'
        return 'primary'

class OrderEvent(models.Model):
    EVENT_TYPES = (
        ('order_created', 'Order Created'),
        ('shipment_created', 'Shipment Created'),
        ('status_updated', 'Status Updated'),
        ('payment_status_updated', 'Payment Status Updated'),
        ('note_added', 'Note Added'),
        ('document_added', 'Document Added'),
    )

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    description = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_number} - {self.get_event_type_display()} - {self.created_at}"

class ManifestItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='manifest_items')
    material = models.CharField(max_length=200)
    weight = models.DecimalField(max_digits=12, decimal_places=2)
    weight_unit = models.CharField(max_length=10, default='lbs')
    
    buy_price = models.DecimalField(max_digits=12, decimal_places=4)
    buy_price_unit = models.CharField(max_length=20, default='per lbs')
    
    sell_price = models.DecimalField(max_digits=12, decimal_places=4)
    sell_price_unit = models.CharField(max_length=20, default='per lbs')
    
    packaging = models.CharField(max_length=100, blank=True)
    is_palletized = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.material} ({self.weight} {self.weight_unit})"

    @property
    def normalized_weight(self):
        """Convert weight to lbs based on weight_unit"""
        from decimal import Decimal
        unit = self.weight_unit.lower()
        if unit == 'lbs':
            return self.weight
        elif unit in ['kg', 'kgs']:
            return self.weight * Decimal('2.20462')
        elif unit == 'mt':
            return self.weight * Decimal('2204.62')
        elif unit == 'st':
            return self.weight * Decimal('2000.0')
        # Fallback for pcs or unknown units
        return self.weight

    @property
    def total_buy_price(self):
        return self.weight * self.buy_price

    @property
    def total_sell_price(self):
        return self.weight * self.sell_price

class OrderDocument(models.Model):
    """Documents attached directly to an Order"""
    DOCUMENT_TYPE_CHOICES = [
        ('po', 'Purchase Order'),
        ('contract', 'Contract'),
        ('invoice', 'Commercial Invoice'),
        ('bol', 'Bill of Lading'),
        ('other', 'Other'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='order_documents/%Y/%m/')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_document_type_display()})"

