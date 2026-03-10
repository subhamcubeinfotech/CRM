from django.contrib import admin
from .models import Order, ManifestItem, Tag, ShippingTerm, PackagingType


@admin.register(ShippingTerm)
class ShippingTermAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(PackagingType)
class PackagingTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'color']
    search_fields = ['name']


class ManifestItemInline(admin.TabularInline):
    model = ManifestItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'supplier', 'receiver', 'status', 'created_at']
    list_filter = ['status', 'payment_status']
    search_fields = ['order_number', 'po_number']
    inlines = [ManifestItemInline]
