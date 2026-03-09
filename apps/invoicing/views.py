"""
Invoicing Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime
from decimal import Decimal

from .models import Invoice, InvoiceLineItem, Payment
from apps.accounts.models import Company
from apps.shipments.models import Shipment


@login_required
def invoice_list(request):
    """List all invoices"""
    invoices = Invoice.objects.select_related('customer', 'shipment').all()
    
    # Status filter
    status = request.GET.get('status')
    if status:
        invoices = invoices.filter(status=status)
    
    # Search
    search = request.GET.get('search')
    if search:
        invoices = invoices.filter(
            Q(invoice_number__icontains=search) |
            Q(customer__name__icontains=search)
        )
    
    # Sorting
    sort_by = request.GET.get('sort', '-invoice_date')
    invoices = invoices.order_by(sort_by)
    
    # Pagination
    paginator = Paginator(invoices, 25)
    page = request.GET.get('page')
    invoices = paginator.get_page(page)
    
    context = {
        'invoices': invoices,
        'status_filter': status,
        'search': search,
        'sort_by': sort_by,
        'status_choices': Invoice.STATUS_CHOICES,
    }
    return render(request, 'invoices/list.html', context)


@login_required
def pending_invoices(request):
    """Pending invoices management page"""
    # Get pending and overdue invoices
    pending = Invoice.objects.filter(
        status__in=['draft', 'sent', 'overdue']
    ).select_related('customer').order_by('due_date')
    
    # Stats
    total_pending = pending.count()
    overdue_count = pending.filter(status='overdue').count()
    total_outstanding = pending.aggregate(total=Sum('balance_due'))['total'] or 0
    overdue_amount = pending.filter(status='overdue').aggregate(total=Sum('balance_due'))['total'] or 0
    
    context = {
        'invoices': pending,
        'total_pending': total_pending,
        'overdue_count': overdue_count,
        'total_outstanding': total_outstanding,
        'overdue_amount': overdue_amount,
    }
    return render(request, 'invoices/pending.html', context)


@login_required
def invoice_detail(request, pk):
    """Invoice detail view"""
    invoice = get_object_or_404(Invoice.objects.select_related('customer', 'shipment'), pk=pk)
    
    context = {
        'invoice': invoice,
        'line_items': invoice.line_items.all(),
        'payments': invoice.payments.all(),
    }
    return render(request, 'invoices/detail.html', context)


@login_required
def invoice_create(request):
    """Create new invoice"""
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        shipment_id = request.POST.get('shipment') or None
        
        invoice = Invoice(
            customer_id=customer_id,
            shipment_id=shipment_id,
            invoice_date=request.POST.get('invoice_date') or timezone.now().date(),
            due_date=request.POST.get('due_date'),
            tax_rate=request.POST.get('tax_rate', 0) or 0,
            notes=request.POST.get('notes', ''),
            terms=request.POST.get('terms', 'Net 30 days'),
            created_by=request.user,
        )
        invoice.save()
        
        # Add line items
        descriptions = request.POST.getlist('description[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        
        for i in range(len(descriptions)):
            if descriptions[i]:
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description=descriptions[i],
                    quantity=quantities[i] if i < len(quantities) else 1,
                    unit_price=unit_prices[i] if i < len(unit_prices) else 0,
                )
        
        # Recalculate totals
        invoice.save()
        
        messages.success(request, f'Invoice {invoice.invoice_number} created successfully!')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    
    customers = Company.objects.filter(company_type='customer', is_active=True)
    shipments = Shipment.objects.filter(status='delivered')
    
    context = {
        'customers': customers,
        'shipments': shipments,
        'today': timezone.now().date(),
    }
    return render(request, 'invoices/form.html', context)


@login_required
def invoice_edit(request, pk):
    """Edit invoice"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if request.method == 'POST':
        invoice.customer_id = request.POST.get('customer')
        invoice.shipment_id = request.POST.get('shipment') or None
        invoice.invoice_date = request.POST.get('invoice_date')
        invoice.due_date = request.POST.get('due_date')
        invoice.tax_rate = request.POST.get('tax_rate', 0) or 0
        invoice.notes = request.POST.get('notes', '')
        invoice.terms = request.POST.get('terms', '')
        invoice.save()
        
        # Update line items
        invoice.line_items.all().delete()
        
        descriptions = request.POST.getlist('description[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        
        for i in range(len(descriptions)):
            if descriptions[i]:
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description=descriptions[i],
                    quantity=quantities[i] if i < len(quantities) else 1,
                    unit_price=unit_prices[i] if i < len(unit_prices) else 0,
                )
        
        # Recalculate totals
        invoice.save()
        
        messages.success(request, f'Invoice {invoice.invoice_number} updated successfully!')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    
    customers = Company.objects.filter(company_type='customer', is_active=True)
    shipments = Shipment.objects.filter(status='delivered')
    
    context = {
        'invoice': invoice,
        'customers': customers,
        'shipments': shipments,
        'line_items': invoice.line_items.all(),
    }
    return render(request, 'invoices/form.html', context)


@login_required
def invoice_print(request, pk):
    """Print invoice view"""
    invoice = get_object_or_404(Invoice.objects.select_related('customer', 'shipment'), pk=pk)
    
    context = {
        'invoice': invoice,
        'line_items': invoice.line_items.all(),
        'is_print': True,
    }
    return render(request, 'invoices/print.html', context)


@login_required
def invoice_pdf(request, pk):
    """Generate PDF invoice"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    # For now, return HTML as PDF placeholder
    # In production, use ReportLab or WeasyPrint
    context = {
        'invoice': invoice,
        'line_items': invoice.line_items.all(),
    }
    response = render(request, 'invoices/print.html', context)
    response['Content-Type'] = 'application/pdf'
    response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
    return response


@login_required
def add_payment(request, pk):
    """Add payment to invoice"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if request.method == 'POST':
        payment = Payment(
            invoice=invoice,
            amount=request.POST.get('amount', 0),
            payment_method=request.POST.get('payment_method', 'check'),
            payment_date=request.POST.get('payment_date') or timezone.now().date(),
            transaction_id=request.POST.get('transaction_id', ''),
            notes=request.POST.get('notes', ''),
            created_by=request.user,
        )
        payment.save()
        
        messages.success(request, f'Payment of ${payment.amount} recorded successfully!')
        return redirect('invoicing:invoice_detail', pk=pk)
    
    context = {
        'invoice': invoice,
        'payment_methods': Payment.PAYMENT_METHOD_CHOICES,
    }
    return render(request, 'invoices/add_payment.html', context)


@login_required
def send_invoice(request, pk):
    """Send invoice to customer"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if request.method == 'POST':
        invoice.status = 'sent'
        invoice.save()
        messages.success(request, f'Invoice {invoice.invoice_number} marked as sent!')
        return redirect('invoicing:invoice_detail', pk=pk)
    
    context = {
        'invoice': invoice,
    }
    return render(request, 'invoices/send_confirm.html', context)
