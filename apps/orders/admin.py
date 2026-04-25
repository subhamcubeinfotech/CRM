from django.contrib import admin
from .models import Order, ManifestItem, Tag, ShippingTerm, PackagingType
from apps.accounts.admin import GlobalVisibilityMixin


@admin.register(ShippingTerm)
class ShippingTermAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['name', 'tenant', 'description']
    list_filter = ['tenant']
    search_fields = ['name']


@admin.register(PackagingType)
class PackagingTypeAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(Tag)
class TagAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['name', 'tenant', 'color']
    list_filter = ['tenant']
    search_fields = ['name']


class ManifestItemInline(admin.TabularInline):
    model = ManifestItem
    extra = 0


@admin.register(Order)
class OrderAdmin(GlobalVisibilityMixin, admin.ModelAdmin):
    list_display = ['order_number', 'tenant', 'supplier', 'receiver', 'status', 'created_at']
    list_filter = ['tenant', 'status', 'payment_status']
    search_fields = ['order_number', 'po_number']
    inlines = [ManifestItemInline]
