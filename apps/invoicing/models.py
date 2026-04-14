"""
Invoicing Models - Invoice management and payments
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta


from apps.accounts.models import TenantAwareModel

class Invoice(TenantAwareModel):
    """Invoice model"""
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('reviewed', 'Reviewed'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Identification
    invoice_number = models.CharField(max_length=50, unique=True)
    
    # Related parties
    customer = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='invoices', limit_choices_to={'company_type': 'customer'})
    shipment = models.OneToOneField('shipments.Shipment', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice')
    
    # Dates
    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)
    
    # Financial
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Tax rate percentage')
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    portal_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    
    # Status and notes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True, default='Net 30 days')
    payment_instructions = models.TextField(blank=True, help_text='Payment instructions for customer')
    tax_details = models.TextField(blank=True, help_text='Tax details and information')
    file_name = models.CharField(max_length=255, blank=True, default='')
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_invoices')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-invoice_date', '-invoice_number']
    
    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name}"
    
    @property
    def balance_due(self):
        """Calculate balance due"""
        return self.total - self.amount_paid
    
    @property
    def days_overdue(self):
        """Calculate days overdue"""
        if self.status in ['paid', 'cancelled']:
            return 0
        if self.due_date < timezone.now().date():
            return (timezone.now().date() - self.due_date).days
        return 0
    
    @property
    def days_until_due(self):
        """Calculate days until due"""
        if self.status in ['paid', 'cancelled']:
            return 0
        if self.due_date >= timezone.now().date():
            return (self.due_date - timezone.now().date()).days
        return 0
    
    @property
    def is_overdue(self):
        """Check if invoice is overdue"""
        return self.status not in ['paid', 'cancelled'] and self.due_date < timezone.now().date()
    
    @property
    def urgency_class(self):
        """Return CSS class for urgency level"""
        if self.is_overdue:
            return 'danger'
        elif self.days_until_due <= 7:
            return 'warning'
        return 'normal'
    
    def save(self, *args, **kwargs):
        # Auto-generate portal token if not set
        if not self.portal_token:
            import secrets
            self.portal_token = secrets.token_urlsafe(32)
            
        # Auto-generate invoice number if not set
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()
        
        # Auto-generate file_name if not set (after invoice_number is available)
        if not self.file_name:
            self.file_name = f'invoice_{self.invoice_number}.pdf'
        
        # Auto-set due date based on customer payment terms if not set
        if not self.due_date:
            payment_terms = self.customer.payment_terms if self.customer else 30
            self.due_date = timezone.now().date() + timedelta(days=payment_terms)
        
        # Calculate totals from line items
        if self.pk:
            self.subtotal = sum(item.total for item in self.line_items.all())
        
        # Calculate tax and total
        from decimal import Decimal
        self.tax_amount = self.subtotal * (self.tax_rate / Decimal('100'))
        self.total = self.subtotal + self.tax_amount
        
        # Update status based on payment
        if self.amount_paid >= self.total and self.total > 0:
            self.status = 'paid'
            if not self.paid_date:
                self.paid_date = timezone.now().date()
        elif self.is_overdue and self.status not in ['paid', 'cancelled']:
            self.status = 'overdue'
        
        super().save(*args, **kwargs)
    
    @classmethod
    def generate_invoice_number(cls, shipment=None):
        """Generate unique invoice number, synced with shipment if possible"""
        from django.db import transaction
        from datetime import date
        
        if shipment and shipment.shipment_number:
            # Sync with shipment number e.g. INV-2026-01707
            # Replace SHP with INV prefix if present
            base_number = shipment.shipment_number
            if base_number.startswith('SHP-'):
                base_number = base_number.replace('SHP-', 'INV-', 1)
            else:
                base_number = f"INV-{base_number}"
            return base_number
            
        with transaction.atomic():
            # Lock table to prevent race conditions
            last_invoice = cls.objects.select_for_update().filter(
                invoice_number__startswith=f'INV-{date.today().year}-'
            ).order_by('-invoice_number').first()
            
            if last_invoice:
                try:
                    # Handle possible UUID suffix from old invoices
                    num_part = last_invoice.invoice_number.split('-')[-1]
                    if '_' in num_part:
                        num_part = num_part.split('_')[0]
                    new_num = int(num_part) + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
                
            return f"INV-{date.today().year}-{new_num:05d}"


class InvoiceLineItem(models.Model):
    """Invoice line items"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.description} - ${self.total}"
    
    def save(self, *args, **kwargs):
        # Calculate total
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class Payment(models.Model):
    """Payment model for invoice payments"""
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('credit_card', 'Credit Card'),
        ('ach', 'ACH/Bank Transfer'),
        ('wire', 'Wire Transfer'),
        ('paypal', 'PayPal'),
    ]
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='check')
    payment_date = models.DateField(default=timezone.now)
    transaction_id = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-payment_date']
    
    def __str__(self):
        return f"Payment of ${self.amount} for {self.invoice.invoice_number}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.invoice.amount_paid = sum(p.amount for p in self.invoice.payments.all())
        self.invoice.save()

class RecurringInvoice(TenantAwareModel):
    """Template for invoices that should be generated periodically"""
    FREQUENCY_CHOICES = [
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]
    
    customer = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='recurring_templates', limit_choices_to={'company_type': 'customer'})
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    
    # Financial Template
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    terms = models.TextField(blank=True, default='Net 30 days')
    payment_instructions = models.TextField(blank=True)
    
    # Scheduling
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    last_generated = models.DateField(null=True, blank=True)
    next_generation_date = models.DateField()
    
    is_active = models.BooleanField(default=True)
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Recurring: {self.customer.name} ({self.frequency})"

    def save(self, *args, **kwargs):
        if not self.next_generation_date:
            self.next_generation_date = self.start_date
        super().save(*args, **kwargs)


class RecurringInvoiceLineItem(models.Model):
    """Line items for recurring invoice templates"""
    recurring_invoice = models.ForeignKey(RecurringInvoice, on_delete=models.CASCADE, related_name='line_items')
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    @property
    def total(self):
        return self.quantity * self.unit_price

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.description} - ${self.total}"


class CreditMemo(TenantAwareModel):
    """Credit memo for refunds or adjustments"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='credit_memos')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=200)
    memo_date = models.DateField(default=timezone.now)
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Credit Memo ${self.amount} for {self.invoice.invoice_number}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update invoice amount paid (credit memo is treated as payment)
        self.invoice.amount_paid = sum(p.amount for p in self.invoice.payments.all()) + \
                                   sum(cm.amount for cm in self.invoice.credit_memos.all())
        self.invoice.save()
