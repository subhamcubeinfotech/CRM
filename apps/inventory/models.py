"""
Inventory Models - Warehouse and inventory management
"""
from django.db import models
from django.conf import settings

from apps.accounts.models import TenantAwareModel


class Warehouse(TenantAwareModel):
    """Warehouse model"""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    
    # Address
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default='USA')
    postal_code = models.CharField(max_length=20)
    
    # Contact
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    
    # Ownership
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='warehouses', null=True, blank=True, help_text="Company this location belongs to")
    
    # Management
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_warehouses')
    is_active = models.BooleanField(default=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Warehouse'
        verbose_name_plural = 'Warehouses'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.code})"
    
    @property
    def full_address(self):
        """Return full address"""
        return f"{self.address}, {self.city}, {self.state} {self.postal_code}, {self.country}"
    
    @property
    def total_items(self):
        """Count total inventory items"""
        return self.inventory_items.count()
    
    @property
    def total_value(self):
        """Calculate total inventory value"""
        return sum(item.total_value for item in self.inventory_items.all())

    @property
    def display_name(self):
        """Pre-formatted name for dropdowns: Priority given to full address if it looks more descriptive"""
        # If we have a full address and the warehouse name is generic (like "Main Office"), 
        # return the full address as it's more useful in a logistics context.
        generic_names = ['Main Office', 'Main Warehouse', 'Warehouse', 'Office', 'Hub']
        
        # Clean the name of company references for checking
        name_clean = self.name
        if self.company:
            name_clean = name_clean.replace(self.company.name, "").strip(" -")
            
        if (not name_clean or name_clean in generic_names) and self.address:
            return self.full_address

        # Otherwise, stick to Company - Name (City) format but include more info
        parts = []
        if self.company:
            parts.append(self.company.name)
        
        name_part = self.name
        if self.company and self.company.name in name_part:
            name_part = name_part.replace(self.company.name, "").strip(" -")
            if not name_part:
                name_part = "Main Office"

        if self.city and "(" not in name_part:
            name_part += f" ({self.city})"
        parts.append(name_part)
        
        return " - ".join(parts)
    
    @property
    def full_display(self):
        """Return full display name"""
        return f"{self.name} - {self.city}, {self.state}"


class Material(TenantAwareModel):
    """Material model for tracking specific material types and grades"""
    name = models.CharField(max_length=200)
    material_type = models.CharField(max_length=100, blank=True, help_text="e.g. PE, PP, PVC")
    grade = models.CharField(max_length=100, blank=True, help_text="e.g. Post-Industrial, Virgin")
    color = models.CharField(max_length=100, blank=True, help_text="e.g. Mixed, Clear, White")
    product_type = models.CharField(max_length=100, blank=True, help_text="e.g. Film, Flake, Regrind")
    
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='materials/', null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        unique_together = ('tenant', 'name')
    
    def __str__(self):
        return self.name


class InventoryItem(TenantAwareModel):
    """Inventory item model"""
    sku = models.CharField(max_length=100, unique=True, verbose_name='SKU')
    product_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Location
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='inventory_items')
    location = models.CharField(max_length=100, blank=True, help_text='Bin or shelf location')
    
    # Quantity
    quantity = models.IntegerField(default=0)
    unit_of_measure = models.CharField(max_length=50, default='pcs')
    
    # Tracking
    lot_number = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    
    # Financial
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Reorder
    reorder_level = models.IntegerField(default=10, help_text='Minimum quantity before reorder')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['sku']
    
    def __str__(self):
        return f"{self.sku} - {self.product_name}"
    
    @property
    def total_value(self):
        """Calculate total value"""
        return self.quantity * self.unit_cost
    
    @property
    def is_low_stock(self):
        """Check if stock is below reorder level"""
        return self.quantity <= self.reorder_level
    
    @property
    def stock_status(self):
        """Return stock status"""
        if self.quantity == 0:
            return 'out_of_stock'
        elif self.is_low_stock:
            return 'low_stock'
        return 'in_stock'

    @property
    def display_stock(self):
        """Pre-formatted stock string for templates"""
        return f"{self.quantity} {self.unit_of_measure} available"
