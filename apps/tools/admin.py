"""
Tools Admin Configuration
"""
from django.contrib import admin
from .models import RateQuote


@admin.register(RateQuote)
class RateQuoteAdmin(admin.ModelAdmin):
    list_display = [
        'carrier_name', 'origin', 'destination', 'shipment_type',
        'total_cost', 'transit_time_display', 'is_best_rate', 'quoted_date'
    ]
    list_filter = ['carrier_name', 'shipment_type', 'service_level', 'is_best_rate']
    search_fields = ['origin', 'destination', 'carrier_name']
    readonly_fields = ['quoted_date']
