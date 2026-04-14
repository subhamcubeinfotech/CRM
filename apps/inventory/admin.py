"""
Inventory Admin Configuration
"""
from django.contrib import admin
from .models import Warehouse, InventoryItem
from apps.accounts.admin import GlobalVisibilityMixin


class InventoryItemInline(admin.TabularInline):
    model = InventoryItem
    extra = 0


@admin.register(Warehouse)
class WarehouseAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['name', 'code', 'company', 'city', 'state', 'manager', 'is_active']
    list_filter = ['is_active', 'company', 'state', 'country']
    search_fields = ['name', 'code', 'company__name', 'city']
    inlines = [InventoryItemInline]


@admin.register(InventoryItem)
class InventoryItemAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = [
        'sku', 'product_name', 'warehouse', 'location', 
        'quantity', 'unit_of_measure', 'unit_cost', 'stock_status', 'image'
    ]
    list_filter = ['warehouse', 'unit_of_measure', 'created_at']
    search_fields = ['sku', 'product_name', 'lot_number', 'serial_number']
    
    def stock_status(self, obj):
        status_colors = {
            'in_stock': 'green',
            'low_stock': 'orange',
            'out_of_stock': 'red'
        }
        color = status_colors.get(obj.stock_status, 'gray')
        return f'<span style="color: {color}; font-weight: bold;">{obj.stock_status.replace("_", " ").title()}</span>'
    stock_status.allow_tags = True
    stock_status.short_description = 'Stock Status'
