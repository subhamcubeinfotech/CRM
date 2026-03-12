"""
Invoicing Admin Configuration
"""
from django.contrib import admin
from .models import Invoice, InvoiceLineItem, Payment


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 1


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ['created_at']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 'customer', 'invoice_date', 'due_date', 
        'total', 'status', 'balance_due', 'file_name'
    ]
    list_filter = ['status', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'customer__name']
    readonly_fields = ['invoice_number', 'created_at', 'updated_at']
    inlines = [InvoiceLineItemInline, PaymentInline]
    
    fieldsets = (
        ('Identification', {
            'fields': ('invoice_number', 'file_name')
        }),
        ('Parties', {
            'fields': ('customer', 'shipment')
        }),
        ('Dates', {
            'fields': ('invoice_date', 'due_date', 'paid_date')
        }),
        ('Financial', {
            'fields': (
                'subtotal', 'tax_rate', 'tax_amount', 'total',
                'amount_paid'
            )
        }),
        ('Status & Notes', {
            'fields': ('status', 'notes', 'terms', 'payment_instructions', 'tax_details')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    @admin.display(description='Balance Due')
    def balance_due(self, obj):
        return f"${obj.balance_due:,.2f}"


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'description', 'quantity', 'unit_price', 'total']
    search_fields = ['description', 'invoice__invoice_number']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'amount', 'payment_method', 'payment_date', 'transaction_id']
    list_filter = ['payment_method', 'payment_date']
    search_fields = ['invoice__invoice_number', 'transaction_id', 'notes']
