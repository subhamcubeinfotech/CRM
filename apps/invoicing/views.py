"""
Invoicing Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, Http404
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from .models import Invoice, InvoiceLineItem, Payment, RecurringInvoice, RecurringInvoiceLineItem, CreditMemo
from apps.accounts.models import Company
from apps.shipments.models import Shipment
from apps.accounts.utils import filter_by_user_company, check_company_access
import logging
from django.http import JsonResponse

logger = logging.getLogger('apps.invoicing')


def _get_invoice(pk):
    """Helper to find invoice by ID or invoice_number"""
    try:
        # Try finding by invoice_number first using plain_objects to bypass tenant filtering
        return Invoice.plain_objects.select_related('customer', 'shipment').get(invoice_number=pk)
    except Invoice.DoesNotExist:
        try:
            # Then by primary key using plain_objects
            return get_object_or_404(Invoice.plain_objects.select_related('customer', 'shipment'), pk=pk)
        except (ValueError, Http404):
            raise Http404("Invoice not found")


@login_required
def invoice_list(request):
    """List all invoices"""
    invoices = filter_by_user_company(
        Invoice.objects.select_related('customer', 'shipment').all(), request.user
    )
    
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
    invoice = _get_invoice(pk)
    
    try:
        check_company_access(invoice.customer, request.user)
        print(f"DEBUG: Access check passed for user: {request.user}")  # Debug line
    except Exception as e:
        print(f"DEBUG: Access check failed: {e}")  # Debug line
        messages.error(request, f'Access denied: {str(e)}')
        return redirect('invoicing:invoice_list')
    
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
        
        if shipment_id:
            # Check for existing invoice using plain_objects to bypass tenant filtering for unique constraint checks
            existing = Invoice.plain_objects.filter(shipment_id=shipment_id).first()
            if existing:
                messages.error(request, f'An invoice already exists for this shipment (Invoice #{existing.invoice_number}).')
                return redirect('invoicing:invoice_create')
        
        invoice = Invoice(
            customer_id=customer_id,
            shipment_id=shipment_id,
            invoice_date=request.POST.get('invoice_date') or timezone.now().date(),
            due_date=request.POST.get('due_date'),
            tax_rate=Decimal(request.POST.get('tax_rate', 0) or 0),
            notes=request.POST.get('notes', ''),
            terms=request.POST.get('terms', 'Net 30 days'),
            payment_instructions=request.POST.get('payment_instructions', ''),
            tax_details=request.POST.get('tax_details', ''),
            file_name=request.POST.get('file_name', ''),
            created_by=request.user,
            tenant=request.user.tenant,
        )
        # Parse dates
        if request.POST.get('invoice_date'):
            try:
                invoice.invoice_date = datetime.strptime(request.POST.get('invoice_date'), '%Y-%m-%d').date()
            except ValueError:
                invoice.invoice_date = timezone.now().date()
        
        if request.POST.get('due_date'):
            try:
                invoice.due_date = datetime.strptime(request.POST.get('due_date'), '%Y-%m-%d').date()
            except ValueError:
                # Default to 30 days if invalid
                invoice.due_date = invoice.invoice_date + timedelta(days=30)
        else:
            # Default to 30 days if missing
            invoice.due_date = invoice.invoice_date + timedelta(days=30)
        
        # Save invoice first
        invoice.save()
        
        # Add line items
        descriptions = request.POST.getlist('description[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        
        for i in range(len(descriptions)):
            if descriptions[i]:
                try:
                    quantity = Decimal(quantities[i] if i < len(quantities) else 1)
                    unit_price = Decimal(unit_prices[i] if i < len(unit_prices) else 0)
                except (ValueError, TypeError):
                    quantity = Decimal('1')
                    unit_price = Decimal('0')
                
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description=descriptions[i],
                    quantity=quantity,
                    unit_price=unit_price,
                    total=quantity * unit_price,
                )
        
        # Recalculate totals
        invoice.save()
        
        messages.success(request, f'Invoice {invoice.invoice_number} created successfully!')
        logger.info(f'Invoice created: {invoice.invoice_number} for customer {invoice.customer} by {request.user}')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    
    customers = Company.objects.filter(company_type='customer', is_active=True)
    # Don't pre-load all shipments - will be loaded via AJAX when customer is selected
    shipments = Shipment.objects.none()
    
    context = {
        'customers': customers,
        'shipments': shipments,
        'today': timezone.now().date(),
    }
    return render(request, 'invoices/form.html', context)


@login_required
def invoice_edit(request, pk):
    """Edit invoice"""
    invoice = _get_invoice(pk)
    
    if request.method == 'POST':
        invoice.customer_id = request.POST.get('customer')
        invoice.shipment_id = request.POST.get('shipment') or None
        invoice.invoice_date = request.POST.get('invoice_date')
        invoice.due_date = request.POST.get('due_date')
        invoice.tax_rate = request.POST.get('tax_rate', 0) or 0
        invoice.notes = request.POST.get('notes', '')
        invoice.terms = request.POST.get('terms', '')
        invoice.payment_instructions = request.POST.get('payment_instructions', '')
        invoice.tax_details = request.POST.get('tax_details', '')
        invoice.file_name = request.POST.get('file_name', '')
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
    # Only load shipments for this customer
    shipments = Shipment.objects.filter(customer=invoice.customer, status='delivered')
    
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
    invoice = _get_invoice(pk)
    
    context = {
        'invoice': invoice,
        'line_items': invoice.line_items.all(),
        'is_print': True,
    }
    return render(request, 'invoices/print.html', context)


def _generate_invoice_pdf_buffer(invoice, request):
    """Internal helper to generate PDF buffer"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from io import BytesIO
    import os

    line_items = list(invoice.line_items.all())

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    # ... (styles omitted for brevity in instruction, but kept in replacement)
    styles = getSampleStyleSheet()
    primary_color = colors.HexColor('#1e40af')
    light_gray = colors.HexColor('#f1f5f9')
    dark_gray = colors.HexColor('#374151')

    # Custom Styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=28, textColor=primary_color, fontName='Helvetica-Bold', leading=34)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#6b7280'), fontName='Helvetica', leading=12)
    normal_style = ParagraphStyle('Normal2', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica', leading=14)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica-Bold', leading=14)
    right_style = ParagraphStyle('Right', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica', alignment=TA_RIGHT, leading=14)
    right_bold_style = ParagraphStyle('RightBold', parent=styles['Normal'], fontSize=11, textColor=dark_gray, fontName='Helvetica-Bold', alignment=TA_RIGHT, leading=16)
    company_style = ParagraphStyle('CompanyStyle', parent=styles['Normal'], fontSize=14, textColor=dark_gray, fontName='Helvetica-Bold', alignment=TA_RIGHT, leading=18)
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#9ca3af'), fontName='Helvetica', alignment=TA_CENTER, leading=12)

    elements = []

    # --- Logo & Header Row ---
    tenant = getattr(invoice, 'tenant', None) or request.user.tenant
    
    # Fallback for admins/superusers generating PDFs on the server
    if not tenant and request.user.is_superuser:
        from apps.accounts.models_tenant import Tenant
        tenant = Tenant.objects.first()

    logo = None
    logo_file = tenant.platform_logo if tenant else None
    
    if not logo_file and request.user.company and request.user.company.logo:
        logo_file = request.user.company.logo
        
    if logo_file:
        try:
            logo_path = logo_file.path
            if os.path.exists(logo_path):
                logo = Image(logo_path)
                aspect = logo.imageHeight / float(logo.imageWidth)
                logo.drawWidth = 35 * mm
                logo.drawHeight = 35 * mm * aspect
        except Exception as e:
            logger.error(f"Error loading logo for PDF: {e}")

    invoice_info = [
        Paragraph("INVOICE", title_style),
        Paragraph(f"<b>INVOICE #:</b> {invoice.invoice_number}", normal_style),
        Paragraph(f"<b>DATE:</b> {invoice.invoice_date.strftime('%m/%d/%Y')}", normal_style),
        Paragraph(f"<b>DUE:</b> {invoice.due_date.strftime('%m/%d/%Y')}", normal_style),
    ]

    # --- Dynamic Branding ---
    my_company = request.user.company
    company_name = my_company.name if my_company else (tenant.display_name if tenant else "FreightPro Logistics")
    company_address = my_company.full_address if my_company else ""
    
    company_info = [
        Paragraph(company_name, company_style),
    ]
    if company_address:
        company_info.append(Paragraph(company_address, right_style))
    if my_company and my_company.phone: company_info.append(Paragraph(my_company.phone, right_style))
    if my_company and my_company.email: company_info.append(Paragraph(my_company.email, right_style))

    # --- Header Table ---
    if logo:
        # Logo on left, Invoice Info in middle, Company Info on right
        header_table = Table([[logo, invoice_info, company_info]], colWidths=[40*mm, 65*mm, 65*mm])
    else:
        header_table = Table([[invoice_info, company_info]], colWidths=[95*mm, 75*mm])
        
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10*mm))
    
    # ─── REFERENCE SECTION ─────────────────────────────
    if invoice.shipment:
        s = invoice.shipment
        ref_data = [
            [Paragraph(f"<b>SHIPMENT ID:</b> {s.shipment_number}", normal_style)],
            [Paragraph(f"<b>ORDER ID:</b> {s.order.order_number if s.order else '-'}", normal_style)],
            [Paragraph(f"<b>PURCHASE ORDER:</b> {s.order.po_number if s.order else '-'}", normal_style)],
        ]
        ref_table = Table(ref_data, colWidths=[170*mm])
        ref_table.setStyle(TableStyle([
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
            ('TOPPADDING', (0,0), (-1,-1), 1),
        ]))
        elements.append(ref_table)
        elements.append(Spacer(1, 6*mm))

    # ─── SOLD TO / SHIP TO BOXES ───────────────────────────
    # Sold To Column
    cust = invoice.customer
    sold_to_content = [
        Paragraph(cust.name, bold_style),
    ]
    if cust.address_line1: sold_to_content.append(Paragraph(cust.address_line1, normal_style))
    if cust.address_line2: sold_to_content.append(Paragraph(cust.address_line2, normal_style))
    city_state = f"{cust.city}, {cust.state} {cust.postal_code}".strip(', ')
    if city_state: sold_to_content.append(Paragraph(city_state, normal_style))
    sold_to_content.append(Paragraph(cust.country or "USA", normal_style))
    if cust.phone: sold_to_content.append(Paragraph(cust.phone, normal_style))

    # Ship To Column
    ship_to_content = []
    if invoice.shipment:
        s = invoice.shipment
        # Use Consignee if available, otherwise Destination details
        ship_name = s.consignee.name if s.consignee else (s.customer.name if not s.consignee else "-")
        ship_to_content.append(Paragraph(ship_name, bold_style))
        
        addr = s.destination_address or (s.consignee.address_line1 if s.consignee else "")
        if addr: ship_to_content.append(Paragraph(addr, normal_style))
        
        city = s.destination_city or (s.consignee.city if s.consignee else "")
        state = s.destination_state or (s.consignee.state if s.consignee else "")
        zip_code = s.destination_postal_code or (s.consignee.postal_code if s.consignee else "")
        csz = f"{city}, {state} {zip_code}".strip(', ')
        if csz: ship_to_content.append(Paragraph(csz, normal_style))
        
        country = s.destination_country or (s.consignee.country if s.consignee else "USA")
        ship_to_content.append(Paragraph(country, normal_style))
        
        phone = s.delivery_contact_phone or (s.consignee.phone if s.consignee else "")
        if phone: ship_to_content.append(Paragraph(phone, normal_style))
        
        # Requirements line
        reqs = s.special_instructions or (s.order.notes if s.order else "")
        if reqs:
            ship_to_content.append(Spacer(1, 2*mm))
            ship_to_content.append(Paragraph(f"<b>Requirements:</b> {reqs}", normal_style))
    else:
        ship_to_content.append(Paragraph("No shipment info", normal_style))

    # Create the tables for the boxes with blue headers
    box_header_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#94a3b8')), # Soft blue-grey like Sagar
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('TOPPADDING', (0,0), (-1,0), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,1), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,1), (-1,-1), 5),
        ('RIGHTPADDING', (0,1), (-1,-1), 5),
        ('TOPPADDING', (0,1), (-1,-1), 5),
        ('BOTTOMPADDING', (0,1), (-1,-1), 10),
    ])

    sold_to_table = Table([["Sold To:"], [sold_to_content]], colWidths=[82*mm])
    sold_to_table.setStyle(box_header_style)
    
    ship_to_table = Table([["Ship To:"], [ship_to_content]], colWidths=[82*mm])
    ship_to_table.setStyle(box_header_style)

    box_container = Table([[sold_to_table, Spacer(1, 6*mm), ship_to_table]], colWidths=[82*mm, 6*mm, 82*mm])
    box_container.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    
    elements.append(box_container)
    elements.append(Spacer(1, 8*mm))

    # ─── LINE ITEMS TABLE ──────────────────────────────────
    item_header = [
        Paragraph("Description", label_style),
        Paragraph("Quantity", label_style),
        Paragraph("Unit Price", label_style),
        Paragraph("Amount", label_style),
    ]
    table_data = [item_header]
    for item in line_items:
        table_data.append([
            Paragraph(item.description, normal_style),
            Paragraph(f"{int(item.quantity) if item.quantity == int(item.quantity) else item.quantity} lbs", normal_style),
            Paragraph(f"${item.unit_price:,.2f} / lbs", normal_style),
            Paragraph(f"${item.total:,.2f}", normal_style),
        ])
    if not line_items:
        table_data.append([Paragraph("No items", normal_style), '', '', ''])

    items_table = Table(table_data, colWidths=[85*mm, 30*mm, 25*mm, 30*mm])
    items_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#94a3b8')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        # Rows
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('TOPPADDING', (0,1), (-1,-1), 4),
        ('BOTTOMPADDING', (0,1), (-1,-1), 4),
        ('ALIGN', (1,1), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4*mm))

    # ─── TOTALS ────────────────────────────────────────────
    total_qty = sum(item.quantity for item in line_items)
    totals_data = [
        [Paragraph("Total Quantity:", bold_style), Paragraph(f"{total_qty:,.2f} lbs", bold_style)],
        [Paragraph("Subtotal:", bold_style), Paragraph(f"${invoice.subtotal:,.2f}", bold_style)],
        [Paragraph("Total Amount:", bold_style), Paragraph(f"${invoice.total:,.2f}", bold_style)],
    ]
    
    totals_table = Table(totals_data, colWidths=[140*mm, 30*mm])
    totals_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'LEFT'),
        ('BACKGROUND', (0,0), (-1,-1), colors.white),
    ]))
    elements.append(totals_table)

    # ─── NOTES ─────────────────────────────────────────────
    if invoice.notes:
        elements.append(Spacer(1, 6*mm))
        elements.append(Paragraph("NOTES", label_style))
        elements.append(Paragraph(invoice.notes, normal_style))

    # ─── FOOTER ────────────────────────────────────────────
    elements.append(Spacer(1, 10*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#d1d5db')))
    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph("Thank you for your business!", footer_style))
    elements.append(Paragraph("FreightPro Logistics | 123 Logistics Way, Chicago, IL 60601 | www.freightpro.com", footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


@login_required
def invoice_pdf(request, pk):
    """Generate a real PDF invoice using helper"""
    invoice = _get_invoice(pk)
    buffer = _generate_invoice_pdf_buffer(invoice, request)
    
    logger.info(f'PDF generated for invoice {invoice.invoice_number} by {request.user}')
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
    return response


@login_required
def add_payment(request, pk):
    """Add payment to invoice"""
    invoice = _get_invoice(pk)
    
    if request.method == 'POST':
        payment_date = request.POST.get('payment_date')
        if payment_date:
            try:
                payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
            except ValueError:
                payment_date = timezone.now().date()
        else:
            payment_date = timezone.now().date()
            
        payment = Payment(
            invoice=invoice,
            amount=Decimal(request.POST.get('amount', 0)),
            payment_method=request.POST.get('payment_method', 'check'),
            payment_date=payment_date,
            transaction_id=request.POST.get('transaction_id', ''),
            notes=request.POST.get('notes', ''),
            created_by=request.user,
        )
        payment.save()
        
        # Notify Customer via Email
        if invoice.customer.email:
            try:
                from django.core.mail import EmailMessage
                from django.conf import settings
                
                subject = f"Payment Received - Invoice {invoice.invoice_number}"
                body = f"""Dear {invoice.customer.name},
                
Thank you for your payment of ${payment.amount:,.2f} recorded on {payment.payment_date.strftime('%m/%d/%Y')}.

Invoice: {invoice.invoice_number}
Amount Paid: ${payment.amount:,.2f}
Remaining Balance: ${invoice.balance_due:,.2f}

You can view the updated invoice and payment history here:
{request.scheme}://{request.get_host()}{reverse('invoicing:public_invoice_detail', kwargs={'token': invoice.portal_token})}

Thank you for your business!
Best regards,
The FreightPro Team"""
                
                email = EmailMessage(
                    subject=subject,
                    body=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[invoice.customer.email],
                )
                email.send(fail_silently=True)
                messages.success(request, f'Payment recorded and confirmation sent to {invoice.customer.email}.')
            except Exception as e:
                logger.error(f'Failed to send payment confirmation: {str(e)}')
                messages.warning(request, f'Payment recorded, but email confirmation failed: {str(e)}')
        else:
            messages.success(request, f'Payment of ${payment.amount} recorded successfully!')
            
        logger.info(f'Payment of ${payment.amount} recorded for invoice {invoice.invoice_number} by {request.user}')
        return redirect('invoicing:invoice_detail', pk=pk)
    
    context = {
        'invoice': invoice,
        'payment_methods': Payment.PAYMENT_METHOD_CHOICES,
    }
    return render(request, 'invoices/add_payment.html', context)


@login_required
def send_invoice(request, pk):
    """Send invoice to customer via email with PDF attachment"""
    from django.core.mail import EmailMessage
    from django.conf import settings
    
    invoice = _get_invoice(pk)
    
    if request.method == 'POST':
        if not invoice.customer.email:
            messages.error(request, f"Customer {invoice.customer.name} does not have an email address!")
            return redirect('invoicing:invoice_detail', pk=pk)
            
        try:
            # 1. Generate PDF
            buffer = _generate_invoice_pdf_buffer(invoice, request)
            
            # 2. Compose Email
            subject = f"Invoice {invoice.invoice_number} from FreightPro Logistics"
            body = f"""Dear {invoice.customer.name},

Please find attached your invoice {invoice.invoice_number} for the amount of ${invoice.total:,.2f}.

Payment is due by {invoice.invoice_date.strftime('%m/%d/%Y')}.

Thank you for your business!

Best regards,
The FreightPro Team"""
            
            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[invoice.customer.email],
            )
            
            # 3. Attach PDF
            email.attach(f"{invoice.invoice_number}.pdf", buffer.getvalue(), 'application/pdf')
            
            # 4. Send
            email.send(fail_silently=False)
            
            # 5. Update Status
            invoice.status = 'sent'
            invoice.save()
            
            messages.success(request, f'Invoice {invoice.invoice_number} sent to {invoice.customer.email} successfully!')
            logger.info(f'Invoice {invoice.invoice_number} emailed to {invoice.customer.email} by {request.user}')
        except Exception as e:
            logger.error(f'Failed to send invoice {invoice.invoice_number}: {str(e)}')
        return redirect('invoicing:invoice_detail', pk=pk)
    
    return redirect('invoicing:invoice_detail', pk=pk)
    
@login_required
def aging_report(request):
    """
    Accounts Receivable Aging Report
    Buckets: Current, 1-30, 31-60, 61-90, 90+ days
    """
    now = timezone.now().date()
    
    # Get all unpaid invoices
    unpaid_invoices = Invoice.objects.filter(
        status__in=['reviewed', 'sent', 'overdue', 'partial']
    ).exclude(status__in=['paid', 'cancelled']).select_related('customer')
    
    # Alternatively, any invoice where balance_due > 0
    # (Using the filter above for safety, but we could also filter by total > amount_paid)
    
    aging_data = []
    customers = Company.objects.filter(invoices__in=unpaid_invoices).distinct()
    
    total_current = Decimal('0')
    total_1_30 = Decimal('0')
    total_31_60 = Decimal('0')
    total_61_90 = Decimal('0')
    total_90_plus = Decimal('0')
    grand_total = Decimal('0')

    for customer in customers:
        cust_invoices = unpaid_invoices.filter(customer=customer)
        
        row = {
            'customer': customer,
            'current': Decimal('0'),
            '1_30': Decimal('0'),
            '31_60': Decimal('0'),
            '61_90': Decimal('0'),
            '90_plus': Decimal('0'),
            'total': Decimal('0'),
        }
        
        for inv in cust_invoices:
            balance = inv.balance_due
            if balance <= 0:
                continue
                
            days = (now - inv.due_date).days if inv.due_date < now else 0
            
            if days <= 0:
                row['current'] += balance
                total_current += balance
            elif days <= 30:
                row['1_30'] += balance
                total_1_30 += balance
            elif days <= 60:
                row['31_60'] += balance
                total_31_60 += balance
            elif days <= 90:
                row['61_90'] += balance
                total_61_90 += balance
            else:
                row['90_plus'] += balance
                total_90_plus += balance
            
            row['total'] += balance
            grand_total += balance
            
        if row['total'] > 0:
            aging_data.append(row)
            
    context = {
        'aging_data': aging_data,
        'report_date': now,
        'totals': {
            'current': total_current,
            '1_30': total_1_30,
            '31_60': total_31_60,
            '61_90': total_61_90,
            '90_plus': total_90_plus,
            'grand_total': grand_total,
        }
    }
    return render(request, 'invoices/aging_report.html', context)

@login_required
def recurring_invoice_list(request):
    """List all recurring invoice templates"""
    templates = RecurringInvoice.objects.filter(tenant=request.user.tenant).select_related('customer')
    context = {
        'templates': templates,
    }
    return render(request, 'invoices/recurring_list.html', context)


@login_required
def recurring_invoice_create(request):
    """Create a new recurring invoice template"""
    if request.method == 'POST':
        customer_id = request.POST.get('customer')
        frequency = request.POST.get('frequency')
        start_date = request.POST.get('start_date') or timezone.now().date()
        tax_rate = Decimal(request.POST.get('tax_rate', 0) or 0)
        terms = request.POST.get('terms', 'Net 30 days')
        
        template = RecurringInvoice.objects.create(
            customer_id=customer_id,
            frequency=frequency,
            start_date=start_date,
            tax_rate=tax_rate,
            terms=terms,
            created_by=request.user,
            tenant=request.user.tenant,
        )
        
        # Add line items
        descriptions = request.POST.getlist('description[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        
        for i in range(len(descriptions)):
            if descriptions[i]:
                RecurringInvoiceLineItem.objects.create(
                    recurring_invoice=template,
                    description=descriptions[i],
                    quantity=Decimal(quantities[i] or 1),
                    unit_price=Decimal(unit_prices[i] or 0),
                )
        
        messages.success(request, 'Recurring invoice template created successfully!')
        return redirect('invoicing:recurring_invoice_list')
        
    customers = Company.objects.filter(company_type='customer', is_active=True)
    context = {
        'customers': customers,
        'frequencies': RecurringInvoice.FREQUENCY_CHOICES,
        'today': timezone.now().date(),
    }
    return render(request, 'invoices/recurring_form.html', context)


@login_required
def trigger_recurring_generation(request):
    """Manually trigger the recurring generation task"""
    from .tasks import process_recurring_invoices
    count = process_recurring_invoices()
    if count > 0:
        messages.success(request, f'Successfully generated {count} recurring invoices.')
    else:
        messages.info(request, 'No invoices were due for generation.')
    return redirect('invoicing:recurring_invoice_list')


@login_required
def add_credit_memo(request, pk):
    """Add a credit memo to an invoice"""
    invoice = _get_invoice(pk)
    
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        reason = request.POST.get('reason', 'Adjustment')
        
        memo = CreditMemo.objects.create(
            invoice=invoice,
            amount=amount,
            reason=reason,
            created_by=request.user,
            tenant=request.user.tenant,
        )
        
        # Notify Customer via Email
        if invoice.customer.email:
            try:
                from django.core.mail import EmailMessage
                from django.conf import settings
                
                subject = f"Credit Memo Applied - Invoice {invoice.invoice_number}"
                body = f"""Dear {invoice.customer.name},
                
A credit memo of ${amount:,.2f} has been applied to your invoice {invoice.invoice_number}.
Reason: {reason}

Updated Balance Due: ${invoice.balance_due:,.2f}

You can view the updated invoice here:
{request.scheme}://{request.get_host()}{reverse('invoicing:public_invoice_detail', kwargs={'token': invoice.portal_token})}

Thank you for your business!
Best regards,
The FreightPro Team"""
                
                email = EmailMessage(
                    subject=subject,
                    body=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[invoice.customer.email],
                )
                email.send(fail_silently=True)
                messages.success(request, f'Credit memo of ${amount} applied and email sent to {invoice.customer.email}.')
            except Exception as e:
                logger.error(f'Failed to send credit memo email: {str(e)}')
                messages.warning(request, f'Credit memo applied, but email failed: {str(e)}')
        else:
            messages.success(request, f'Credit memo of ${amount} applied successfully.')
            
        return redirect('invoicing:invoice_detail', pk=pk)
        
    context = {
        'invoice': invoice,
    }
    return render(request, 'invoices/add_credit_memo.html', context)

@login_required
def update_invoice_status(request, pk):
    """Update invoice status (e.g. Draft -> Reviewed)"""
    if request.method == 'POST':
        invoice = _get_invoice(pk)
        new_status = request.POST.get('status')
        
        if new_status in dict(Invoice.STATUS_CHOICES):
            invoice.status = new_status
            invoice.save()
            messages.success(request, f'Invoice status updated to {invoice.get_status_display()}.')
        else:
            messages.error(request, 'Invalid status.')
            
        return redirect('invoicing:invoice_detail', pk=pk)
    
    return redirect('invoicing:invoice_list')


def public_invoice_detail(request, token):
    """Public view of an invoice via a secure token"""
    try:
        invoice = Invoice.objects.get(portal_token=token)
    except Invoice.DoesNotExist:
        return HttpResponse('Invalid or expired invoice link.', status=404)
        
    context = {
        'invoice': invoice,
        'line_items': invoice.line_items.all(),
        'payments': invoice.payments.all(),
        'public_view': True,
    }
    return render(request, 'invoices/public_detail.html', context)


@login_required
def get_customer_shipments(request, customer_id):
    """AJAX view to get delivered shipments for a specific customer"""
    shipments = Shipment.objects.filter(
        customer_id=customer_id, 
        status='delivered'
    ).order_by('-created_at')
    
    data = [
        {
            'id': s.id,
            'shipment_number': s.shipment_number,
            'origin': s.origin_city,
            'destination': s.destination_city
        } for s in shipments
    ]
    return JsonResponse({'shipments': data})
