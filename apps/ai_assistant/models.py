"""
AI Assistant Models - Chat sessions, pending inventory, buyer requirements
"""
# Models last refreshed to ensure field synchronization
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
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=500)
    body_text = models.TextField()
    received_at = models.DateTimeField()
    message_id = models.CharField(max_length=500, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    matched_company = models.ForeignKey('accounts.Company', on_delete=models.SET_NULL, null=True, blank=True)
    raw_extraction = models.JSONField(default=dict, blank=True, help_text='Raw LLM extraction output')
    sentiment_label = models.CharField(max_length=20, default='neutral')
    sentiment_score = models.FloatField(default=0.0, help_text='-1.0 (negative) to +1.0 (positive)')
    priority_level = models.CharField(max_length=20, default='medium')
    sentiment_reason = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_emails')
    fetched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='fetched_emails')
    mailbox_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_inbox_emails')
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


class DemandForecastSnapshot(TenantAwareModel):
    """Snapshot of predicted inventory depletion for proactive planning."""
    ALERT_LEVEL_CHOICES = [
        ('healthy', 'Healthy'),
        ('watch', 'Watch'),
        ('risk', 'Risk'),
        ('critical', 'Critical'),
    ]

    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.CASCADE, related_name='forecast_snapshots')
    current_quantity = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    avg_daily_usage = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    days_to_runout = models.IntegerField(null=True, blank=True)
    predicted_runout_date = models.DateField(null=True, blank=True)
    confidence_score = models.FloatField(default=0.0)
    alert_level = models.CharField(max_length=20, choices=ALERT_LEVEL_CHOICES, default='healthy')
    notes = models.TextField(blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['days_to_runout', '-computed_at']
        unique_together = ('tenant', 'inventory_item')

    def __str__(self):
        return f"{self.inventory_item.sku} -> {self.days_to_runout or 'N/A'} days"


class QuoteDraft(TenantAwareModel):
    """Auto-drafted quote generated from a smart match."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    smart_match = models.ForeignKey(SmartMatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='quote_drafts')
    requirement = models.ForeignKey(BuyerRequirement, on_delete=models.CASCADE, related_name='quote_drafts')
    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.CASCADE, related_name='quote_drafts')
    buyer = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='incoming_quote_drafts')
    supplier = models.ForeignKey('accounts.Company', on_delete=models.SET_NULL, null=True, blank=True, related_name='outgoing_quote_drafts')
    quantity = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, default='lbs')
    supplier_unit_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    markup_percent = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    quoted_unit_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    total_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    subject = models.CharField(max_length=255)
    body_text = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_quote_drafts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Quote {self.id} for {self.requirement.material_name}"


class DocumentVisionRecord(TenantAwareModel):
    """OCR + structured extraction output for uploaded logistics documents."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    SOURCE_CHOICES = [
        ('general', 'General Upload'),
        ('shipment', 'Shipment Document'),
        ('order', 'Order Document'),
        ('company', 'Company Document'),
    ]

    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='general')
    shipment_document = models.ForeignKey('shipments.Document', on_delete=models.SET_NULL, null=True, blank=True, related_name='vision_records')
    order_document = models.ForeignKey('orders.OrderDocument', on_delete=models.SET_NULL, null=True, blank=True, related_name='vision_records')
    company_document = models.ForeignKey('accounts.CompanyDocument', on_delete=models.SET_NULL, null=True, blank=True, related_name='vision_records')
    uploaded_file = models.FileField(upload_to='ai_vision/%Y/%m/', null=True, blank=True)
    extracted_text = models.TextField(blank=True)
    extracted_json = models.JSONField(default=dict, blank=True)
    confidence_score = models.FloatField(default=0.0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='vision_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Vision #{self.id} ({self.status})"
