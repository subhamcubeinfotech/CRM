from django.contrib import admin
from .models import (
    ChatSession, ChatMessage,
    PendingInventoryEmail, PendingInventoryItem,
    BuyerRequirement, SmartMatch,
    DemandForecastSnapshot, QuoteDraft, DocumentVisionRecord
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
    list_display = ['subject', 'sender_email', 'recipient_email', 'mailbox_user', 'status', 'priority_level', 'sentiment_label', 'received_at', 'tenant']
    list_filter = ['status', 'priority_level', 'sentiment_label', 'tenant']

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


@admin.register(DemandForecastSnapshot)
class DemandForecastSnapshotAdmin(admin.ModelAdmin):
    list_display = ['inventory_item', 'alert_level', 'days_to_runout', 'avg_daily_usage', 'predicted_runout_date', 'tenant']
    list_filter = ['alert_level', 'tenant']
    search_fields = ['inventory_item__sku', 'inventory_item__product_name']


@admin.register(QuoteDraft)
class QuoteDraftAdmin(admin.ModelAdmin):
    list_display = ['id', 'buyer', 'supplier', 'quoted_unit_price', 'total_amount', 'status', 'created_at']
    list_filter = ['status', 'tenant']
    search_fields = ['subject', 'buyer__name', 'supplier__name', 'inventory_item__product_name']


@admin.register(DocumentVisionRecord)
class DocumentVisionRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'source_type', 'status', 'confidence_score', 'created_at', 'tenant']
    list_filter = ['source_type', 'status', 'tenant']
