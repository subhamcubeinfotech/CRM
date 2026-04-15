"""
Shipments Admin Configuration
"""
from django.contrib import admin
from .models import Shipment, Container, ShipmentMilestone, Document, ShipmentItem
from apps.accounts.admin import GlobalVisibilityMixin


class ContainerInline(admin.TabularInline):
    model = Container
    extra = 0


class ShipmentMilestoneInline(admin.TabularInline):
    model = ShipmentMilestone
    extra = 0
    readonly_fields = ['timestamp']


class DocumentInline(admin.TabularInline):
    model = Document
    extra = 0
    readonly_fields = ['uploaded_at']


class ShipmentItemInline(admin.TabularInline):
    model = ShipmentItem
    extra = 0
    fields = ['inventory_item', 'material_name', 'weight', 'weight_unit', 'packaging', 'pieces', 'sell_price', 'price_unit']


@admin.register(Shipment)
class ShipmentAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = [
        'shipment_number', 'customer', 'origin_city', 'destination_city', 
        'status', 'shipment_type', 'created_at'
    ]
    list_filter = [
        'status', 'shipment_type', 'is_hazmat', 'is_temperature_controlled',
        'created_at', 'pickup_date'
    ]
    search_fields = [
        'shipment_number', 'tracking_number', 'booking_number',
        'customer__name', 'origin_city', 'destination_city'
    ]
    readonly_fields = [
        'shipment_number', 'gross_profit', 'profit_margin', 
        'created_at', 'updated_at'
    ]
    inlines = [ShipmentItemInline, ContainerInline, ShipmentMilestoneInline, DocumentInline]
    
    fieldsets = (
        ('Identification', {
            'fields': ('shipment_number', 'order', 'tracking_number', 'booking_number')
        }),
        ('Parties', {
            'fields': ('customer', 'carrier', 'shipper', 'consignee')
        }),
        ('Shipment Details', {
            'fields': ('shipment_type', 'status')
        }),
        ('Pickup Details', {
            'fields': (
                'pickup_location', 'pickup_contact', 'pickup_email', 'pickup_number', 'pickup_appointment_type'
            )
        }),
        ('Origin', {
            'fields': (
                'origin_address', 'origin_city', 'origin_state', 
                'origin_country', 'origin_postal_code',
                'origin_latitude', 'origin_longitude'
            )
        }),
        ('Delivery Details', {
            'fields': (
                'delivery_contact', 'delivery_email', 'delivery_number', 'delivery_appointment_type'
            )
        }),
        ('Destination', {
            'fields': (
                'destination_address', 'destination_city', 'destination_state',
                'destination_country', 'destination_postal_code',
                'destination_latitude', 'destination_longitude'
            )
        }),
        ('Commercial', {
            'fields': ('shipping_terms', 'representative', 'tags')
        }),
        ('Current Location', {
            'fields': ('current_latitude', 'current_longitude'),
            'classes': ('collapse',)
        }),
        ('Schedule', {
            'fields': ('pickup_date', 'estimated_delivery_date', 'actual_delivery_date')
        }),
        ('Cargo', {
            'fields': (
                'total_weight', 'total_volume', 'number_of_pieces', 
                'commodity_description'
            )
        }),
        ('Special Requirements', {
            'fields': ('is_hazmat', 'is_temperature_controlled', 'requires_insurance')
        }),
        ('Financial', {
            'fields': (
                'quoted_amount', 'cost', 'revenue',
                'gross_profit', 'profit_margin'
            )
        }),
        ('Notes', {
            'fields': ('special_instructions', 'internal_notes'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def gross_profit(self, obj):
        return f"${obj.gross_profit:,.2f}"
    gross_profit.short_description = 'Gross Profit'
    
    def profit_margin(self, obj):
        return f"{obj.profit_margin:.1f}%"
    profit_margin.short_description = 'Profit Margin'


@admin.register(Container)
class ContainerAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['container_number', 'shipment', 'size', 'weight']
    list_filter = ['size']
    search_fields = ['container_number', 'seal_number', 'shipment__shipment_number']


@admin.register(ShipmentMilestone)
class ShipmentMilestoneAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['shipment', 'status', 'location', 'timestamp']
    list_filter = ['status', 'timestamp']
    search_fields = ['shipment__shipment_number', 'location', 'status']
    readonly_fields = ['timestamp']


@admin.register(Document)
class DocumentAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['title', 'shipment', 'document_type', 'uploaded_by', 'uploaded_at']
    list_filter = ['document_type', 'uploaded_at']
    search_fields = ['title', 'shipment__shipment_number']
    readonly_fields = ['uploaded_at']
