"""
AI Assistant Models - Chat sessions, pending inventory, buyer requirements
"""
from django.db import models
from django.conf import settings
from apps.accounts.models import TenantAwareModel


# ─── FEATURE A: Chat Assistant ──────────────────────────────────────────────

class ChatSession(TenantAwareModel):
    """A chat conversation session"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=200, default='New Chat')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Chat: {self.title} ({self.user.username})"


class ChatMessage(models.Model):
    """Individual message in a chat session"""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True, help_text='Extra data like query results, function calls')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"


# ─── FEATURE B: Pending Inventory from Email ────────────────────────────────

class PendingInventoryEmail(TenantAwareModel):
    """An ingested email containing inventory data"""
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('partial', 'Partially Approved'),
    ]
    sender_email = models.EmailField()
    sender_name = models.CharField(max_length=200, blank=True)
    subject = models.CharField(max_length=500)
    body_text = models.TextField()
    received_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    matched_company = models.ForeignKey('accounts.Company', on_delete=models.SET_NULL, null=True, blank=True)
    raw_extraction = models.JSONField(default=dict, blank=True, help_text='Raw LLM extraction output')
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_emails')
    fetched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='fetched_emails')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"Email: {self.subject} from {self.sender_email}"


class PendingInventoryItem(models.Model):
    """A single extracted inventory item from an email"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    email = models.ForeignKey(PendingInventoryEmail, on_delete=models.CASCADE, related_name='items')
    product_name = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True, default='lbs')
    price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    price_unit = models.CharField(max_length=30, blank=True, default='per lbs')
    material_type = models.CharField(max_length=100, blank=True)
    grade = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    # Link to created inventory item after approval
    created_inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.product_name} ({self.quantity} {self.unit})"


# ─── FEATURE C: Smart Matching ──────────────────────────────────────────────

class BuyerRequirement(TenantAwareModel):
    """A parsed buyer requirement (from email or manual entry)"""
    SOURCE_CHOICES = [
        ('email', 'Email'),
        ('manual', 'Manual'),
    ]
    buyer = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='requirements')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    source_email = models.ForeignKey(PendingInventoryEmail, on_delete=models.SET_NULL, null=True, blank=True)
    material_name = models.CharField(max_length=300)
    material_type = models.CharField(max_length=100, blank=True)
    quantity_needed = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True, default='lbs')
    max_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    notes = models.TextField(blank=True)
    is_fulfilled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.buyer.name} needs {self.material_name}"


class SmartMatch(TenantAwareModel):
    """A match between a buyer requirement and available inventory"""
    requirement = models.ForeignKey(BuyerRequirement, on_delete=models.CASCADE, related_name='matches')
    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.CASCADE, related_name='smart_matches')
    confidence_score = models.FloatField(default=0, help_text='0-100 match confidence')
    match_reason = models.TextField(blank=True)
    is_dismissed = models.BooleanField(default=False)
    is_quoted = models.BooleanField(default=False)
    is_notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-confidence_score']

    def __str__(self):
        return f"Match: {self.requirement.material_name} <-> {self.inventory_item.product_name} ({self.confidence_score}%)"
