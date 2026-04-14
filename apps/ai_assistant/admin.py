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
    list_display = ['subject', 'sender_email', 'status', 'received_at']
    list_filter = ['status']


@admin.register(PendingInventoryItem)
class PendingInventoryItemAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'quantity', 'unit', 'price', 'status']
    list_filter = ['status']


@admin.register(BuyerRequirement)
class BuyerRequirementAdmin(admin.ModelAdmin):
    list_display = ['buyer', 'material_name', 'quantity_needed', 'source', 'is_fulfilled']
    list_filter = ['source', 'is_fulfilled']


@admin.register(SmartMatch)
class SmartMatchAdmin(admin.ModelAdmin):
    list_display = ['requirement', 'inventory_item', 'confidence_score', 'is_dismissed']
    list_filter = ['is_dismissed']
