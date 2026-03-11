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
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Identification
    invoice_number = models.CharField(max_length=50, unique=True)
    
    # Related parties
    customer = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='invoices', limit_choices_to={'company_type': 'customer'})
    shipment = models.ForeignKey('shipments.Shipment', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    
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
    
    # Status and notes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True, default='Net 30 days')
    file_name = models.CharField(max_length=255)
    
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
    
    @staticmethod
    def generate_invoice_number():
        """Generate unique invoice number"""
        year = datetime.now().year
        last_invoice = Invoice.objects.filter(invoice_number__startswith=f'INV-{year}').order_by('-invoice_number').first()
        if last_invoice:
            try:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        return f"INV-{year}-{new_num:05d}"


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
        # Update invoice amount paid
        self.invoice.amount_paid = sum(p.amount for p in self.invoice.payments.all())
        self.invoice.save()
