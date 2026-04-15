from django.contrib import admin
from .models import (
    ChatSession, ChatMessage,
    PendingInventoryEmail, PendingInventoryItem,
    BuyerRequirement, SmartMatch
)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'is_active', 'created_at']
    list_filter = ['is_active']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['session', 'role', 'content_preview', 'created_at']
    list_filter = ['role']

    def content_preview(self, obj):
        return obj.content[:80]


@admin.register(PendingInventoryEmail)
class PendingInventoryEmailAdmin(admin.ModelAdmin):
    list_display = ['subject', 'sender_email', 'status', 'received_at', 'tenant']
    list_filter = ['status', 'tenant']

    def get_queryset(self, request):
        if request.user.is_superuser:
            return PendingInventoryEmail.plain_objects.all()
        return super().get_queryset(request)


@admin.register(PendingInventoryItem)
class PendingInventoryItemAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'quantity', 'unit', 'price', 'status']
    list_filter = ['status']


@admin.register(BuyerRequirement)
class BuyerRequirementAdmin(admin.ModelAdmin):
    list_display = ['buyer', 'material_name', 'quantity_needed', 'source', 'is_fulfilled', 'tenant']
    list_filter = ['source', 'is_fulfilled', 'tenant']

    def get_queryset(self, request):
        if request.user.is_superuser:
            return BuyerRequirement.plain_objects.all()
        return super().get_queryset(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if request.user.is_superuser:
            from apps.accounts.models import Company, Tenant
            if db_field.name == "buyer":
                kwargs["queryset"] = Company.plain_objects.all()
            if db_field.name == "tenant":
                kwargs["queryset"] = Tenant.objects.all()
            if db_field.name == "source_email":
                from .models import PendingInventoryEmail
                kwargs["queryset"] = PendingInventoryEmail.plain_objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(SmartMatch)
class SmartMatchAdmin(admin.ModelAdmin):
    list_display = ['requirement', 'inventory_item', 'confidence_score', 'is_dismissed']
    list_filter = ['is_dismissed']
