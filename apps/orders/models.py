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
    total_weight_target = models.DecimalField(max_digits=15, decimal_places=2, help_text="Target weight in lbs")
    
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

    @property
    def shipped_weight(self):
        """Calculate total weight shipped across all associated shipments"""
        return sum(s.total_weight for s in self.shipments.all())

    @property
    def total_pieces(self):
        """Calculate total pieces from manifest items where unit is pcs"""
        return sum(item.weight for item in self.manifest_items.filter(weight_unit='pcs'))

    @property
    def total_manifest_weight(self):
        """Calculate total weight from manifest items where unit is not pcs"""
        return sum(item.weight for item in self.manifest_items.exclude(weight_unit='pcs'))

    @property
    def weight_progress_percentage(self):
        """Calculate weight progress percentage"""
        if self.total_weight_target > 0:
            return min(int((self.shipped_weight / self.total_weight_target) * 100), 100)
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
    def total_buy_price(self):
        return self.weight * self.buy_price

    @property
    def total_sell_price(self):
        return self.weight * self.sell_price
