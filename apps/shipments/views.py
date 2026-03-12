"""
Shipments Views - Main views for shipment management
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import json

from .models import Shipment, Container, ShipmentMilestone, Document
from apps.accounts.models import Company
from apps.invoicing.models import Invoice
from apps.accounts.utils import filter_by_user_company, check_company_access
import logging

logger = logging.getLogger('apps.shipments')



@login_required
def dashboard(request):
    """Main dashboard view"""
    # Get date ranges
    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_6_months = today - timedelta(days=180)
    
    # Base queryset filtered by user's company
    base_qs = filter_by_user_company(Shipment.objects.all(), request.user)
    invoice_qs = filter_by_user_company(Invoice.objects.all(), request.user)
    
    # Stat cards
    active_shipments = base_qs.filter(
        status__in=['booked', 'picked_up', 'in_transit', 'customs', 'out_for_delivery']
    ).count()
    
    monthly_revenue = base_qs.filter(
        status='delivered',
        actual_delivery_date__gte=month_start
    ).aggregate(total=Sum('revenue'))['total'] or 0
    
    pending_invoices = invoice_qs.filter(
        status__in=['draft', 'sent', 'overdue']
    )
    pending_invoices_count = pending_invoices.count()
    pending_invoices_total = pending_invoices.annotate(
        calculated_balance=F('total') - F('amount_paid')
    ).aggregate(total=Sum('calculated_balance'))['total'] or 0
    
    # On-time delivery rate
    delivered_shipments = base_qs.filter(status='delivered')
    total_delivered = delivered_shipments.count()
    on_time_delivered = delivered_shipments.filter(
        actual_delivery_date__lte=models.F('estimated_delivery_date')
    ).count()
    on_time_rate = (on_time_delivered / total_delivered * 100) if total_delivered > 0 else 0
    
    # Revenue trend (last 6 months)
    months = []
    revenue_data = []
    for i in range(5, -1, -1):
        month_date = today - timedelta(days=i*30)
        month_start_date = month_date.replace(day=1)
        month_end_date = (month_start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        month_revenue = base_qs.filter(
            status='delivered',
            actual_delivery_date__gte=month_start_date,
            actual_delivery_date__lte=month_end_date
        ).aggregate(total=Sum('revenue'))['total'] or 0
        
        months.append(month_date.strftime('%b'))
        revenue_data.append(float(month_revenue))
    
    # Shipment status distribution
    status_counts = base_qs.values('status').annotate(count=Count('id'))
    status_data = {
        'in_transit': 0,
        'delivered': 0,
        'customs': 0,
        'booked': 0,
    }
    for item in status_counts:
        if item['status'] in ['in_transit', 'picked_up', 'out_for_delivery']:
            status_data['in_transit'] += item['count']
        elif item['status'] == 'delivered':
            status_data['delivered'] = item['count']
        elif item['status'] == 'customs':
            status_data['customs'] = item['count']
        elif item['status'] == 'booked':
            status_data['booked'] = item['count']
    
    # Recent shipments
    recent_shipments = base_qs.select_related('customer').order_by('-created_at')[:10]
    
    context = {
        # Stats
        'active_shipments': active_shipments,
        'monthly_revenue': monthly_revenue,
        'pending_invoices_count': pending_invoices_count,
        'pending_invoices_total': pending_invoices_total,
        'on_time_rate': round(on_time_rate, 1),
        
        # Chart data
        'revenue_labels': json.dumps(months),
        'revenue_data': json.dumps(revenue_data),
        'status_data': json.dumps(list(status_data.values())),
        'status_labels': json.dumps(['In Transit', 'Delivered', 'Customs', 'Booked']),
        
        # Recent shipments
        'recent_shipments': recent_shipments,
    }
    return render(request, 'dashboard.html', context)


@login_required
def shipment_list(request):
    """List all shipments with filters"""
    shipments = filter_by_user_company(
        Shipment.objects.select_related('customer').all(), request.user
    )
    
    # Search
    search = request.GET.get('search')
    if search:
        shipments = shipments.filter(
            Q(shipment_number__icontains=search) |
            Q(tracking_number__icontains=search) |
            Q(customer__name__icontains=search)
        )
    
    # Status filter
    status = request.GET.get('status')
    if status:
        shipments = shipments.filter(status=status)
    
    # Type filter
    shipment_type = request.GET.get('type')
    if shipment_type:
        shipments = shipments.filter(shipment_type=shipment_type)
    
    # Date range filter
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        shipments = shipments.filter(pickup_date__gte=date_from)
    if date_to:
        shipments = shipments.filter(pickup_date__lte=date_to)
    
    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    shipments = shipments.order_by(sort_by)
    
    # Pagination
    paginator = Paginator(shipments, 25)
    page = request.GET.get('page')
    shipments = paginator.get_page(page)
    
    context = {
        'shipments': shipments,
        'search': search,
        'status_filter': status,
        'type_filter': shipment_type,
        'date_from': date_from,
        'date_to': date_to,
        'sort_by': sort_by,
        'status_choices': Shipment.STATUS_CHOICES,
        'type_choices': Shipment.SHIPMENT_TYPE_CHOICES,
    }
    return render(request, 'shipments/list.html', context)


@login_required
def shipment_detail(request, pk):
    """Shipment detail view with tracking map"""
    # Filter by tenant first to avoid 404s for shipments in other tenants
    shipment_queryset = Shipment.objects.select_related('customer', 'carrier', 'shipper', 'consignee')
    if request.user.tenant:
        shipment_queryset = shipment_queryset.filter(tenant=request.user.tenant)
    
    shipment = get_object_or_404(shipment_queryset, pk=pk)
    check_company_access(shipment.customer, request.user)
    
    # Get milestones
    milestones = shipment.milestones.all()
    
    # Get documents
    documents = shipment.documents.all()
    
    # Get containers
    containers = shipment.containers.all()
    
    # Get related invoices
    invoices = shipment.invoices.all()
    
    # Prepare map data
    map_data = {
        'origin': {
            'lat': float(shipment.origin_latitude) if shipment.origin_latitude else None,
            'lng': float(shipment.origin_longitude) if shipment.origin_longitude else None,
            'city': shipment.origin_city,
        },
        'destination': {
            'lat': float(shipment.destination_latitude) if shipment.destination_latitude else None,
            'lng': float(shipment.destination_longitude) if shipment.destination_longitude else None,
            'city': shipment.destination_city,
        },
        'current': {
            'lat': float(shipment.current_latitude) if shipment.current_latitude else None,
            'lng': float(shipment.current_longitude) if shipment.current_longitude else None,
        },
    }
    
    context = {
        'shipment': shipment,
        'milestones': milestones,
        'documents': documents,
        'containers': containers,
        'invoices': invoices,
        'map_data': json.dumps(map_data),
    }
    return render(request, 'shipments/detail.html', context)


@login_required
def shipment_create(request):
    """Create new shipment - must be linked to an order"""
    from apps.orders.models import Order

    # Enforce order linkage: require order_id in GET or POST
    order_id = request.GET.get('order_id') or request.POST.get('order_id')
    if not order_id:
        messages.error(request, 'Shipments must be created from within an Order.')
        return redirect('orders:order_list')

    order = get_object_or_404(Order, pk=order_id)

    if request.method == 'POST':
        # Get form data
        customer_id = request.POST.get('customer') or order.receiver_id  # Default to order receiver
        carrier_id = request.POST.get('carrier')
        shipper_id = request.POST.get('shipper') or order.supplier_id  # Default to order supplier
        consignee_id = request.POST.get('consignee')
        
        # Create shipment
        shipment = Shipment(
            order=order,
            customer_id=customer_id,
            carrier_id=carrier_id or None,
            shipper_id=shipper_id or None,
            consignee_id=consignee_id or None,
            shipment_type=request.POST.get('shipment_type', 'road'),
            status='draft',
            
            # Origin
            origin_address=request.POST.get('origin_address', ''),
            origin_city=request.POST.get('origin_city', ''),
            origin_state=request.POST.get('origin_state', ''),
            origin_country=request.POST.get('origin_country', 'USA'),
            origin_postal_code=request.POST.get('origin_postal_code', ''),
            
            # Destination
            destination_address=request.POST.get('destination_address', ''),
            destination_city=request.POST.get('destination_city', ''),
            destination_state=request.POST.get('destination_state', ''),
            destination_country=request.POST.get('destination_country', 'USA'),
            destination_postal_code=request.POST.get('destination_postal_code', ''),
            
            # Schedule
            pickup_date=request.POST.get('pickup_date') or None,
            estimated_delivery_date=request.POST.get('estimated_delivery_date') or None,
            
            # Cargo
            total_weight=request.POST.get('total_weight', 0) or 0,
            total_volume=request.POST.get('total_volume', 0) or 0,
            number_of_pieces=request.POST.get('number_of_pieces', 1) or 1,
            commodity_description=request.POST.get('commodity_description', ''),
            
            # Special requirements
            is_hazmat=request.POST.get('is_hazmat') == 'on',
            is_temperature_controlled=request.POST.get('is_temperature_controlled') == 'on',
            requires_insurance=request.POST.get('requires_insurance') == 'on',
            
            # Financial
            quoted_amount=request.POST.get('quoted_amount', 0) or 0,
            cost=request.POST.get('cost', 0) or 0,
            revenue=request.POST.get('revenue', 0) or 0,
            
            # Notes
            special_instructions=request.POST.get('special_instructions', ''),
            internal_notes=request.POST.get('internal_notes', ''),
            
            # Metadata
            created_by=request.user,
            tenant=request.user.tenant,  # Add tenant assignment
        )
        shipment.save()
        
        # Create initial milestone
        ShipmentMilestone.objects.create(
            shipment=shipment,
            status='Shipment Created',
            location=shipment.origin_city,
            notes='Shipment created in system',
            created_by=request.user
        )
        
        logger.info(f'Shipment created: {shipment.shipment_number} for {shipment.customer} by {request.user}')
        messages.success(request, f'Shipment {shipment.shipment_number} created successfully!')
        return redirect('shipments:shipment_detail', pk=shipment.pk)
    
    # Get companies for dropdowns
    customers = Company.objects.filter(company_type='customer', is_active=True)
    carriers = Company.objects.filter(company_type='carrier', is_active=True)
    all_companies = Company.objects.filter(is_active=True)
    
    context = {
        'order': order,
        'customers': customers,
        'carriers': carriers,
        'all_companies': all_companies,
        'shipment_types': Shipment.SHIPMENT_TYPE_CHOICES,
        'is_create': True,
    }
    return render(request, 'shipments/form.html', context)


@login_required
def shipment_edit(request, pk):
    """Edit existing shipment"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    if request.method == 'POST':
        # Update shipment
        shipment.customer_id = request.POST.get('customer')
        shipment.carrier_id = request.POST.get('carrier') or None
        shipment.shipper_id = request.POST.get('shipper') or None
        shipment.consignee_id = request.POST.get('consignee') or None
        shipment.shipment_type = request.POST.get('shipment_type', 'road')
        
        # Origin
        shipment.origin_address = request.POST.get('origin_address', '')
        shipment.origin_city = request.POST.get('origin_city', '')
        shipment.origin_state = request.POST.get('origin_state', '')
        shipment.origin_country = request.POST.get('origin_country', 'USA')
        shipment.origin_postal_code = request.POST.get('origin_postal_code', '')
        
        # Destination
        shipment.destination_address = request.POST.get('destination_address', '')
        shipment.destination_city = request.POST.get('destination_city', '')
        shipment.destination_state = request.POST.get('destination_state', '')
        shipment.destination_country = request.POST.get('destination_country', 'USA')
        shipment.destination_postal_code = request.POST.get('destination_postal_code', '')
        
        # Schedule
        shipment.pickup_date = request.POST.get('pickup_date') or None
        shipment.estimated_delivery_date = request.POST.get('estimated_delivery_date') or None
        
        # Cargo
        shipment.total_weight = request.POST.get('total_weight', 0) or 0
        shipment.total_volume = request.POST.get('total_volume', 0) or 0
        shipment.number_of_pieces = request.POST.get('number_of_pieces', 1) or 1
        shipment.commodity_description = request.POST.get('commodity_description', '')
        
        # Special requirements
        shipment.is_hazmat = request.POST.get('is_hazmat') == 'on'
        shipment.is_temperature_controlled = request.POST.get('is_temperature_controlled') == 'on'
        shipment.requires_insurance = request.POST.get('requires_insurance') == 'on'
        
        # Financial
        shipment.quoted_amount = request.POST.get('quoted_amount', 0) or 0
        shipment.cost = request.POST.get('cost', 0) or 0
        shipment.revenue = request.POST.get('revenue', 0) or 0
        
        # Notes
        shipment.special_instructions = request.POST.get('special_instructions', '')
        shipment.internal_notes = request.POST.get('internal_notes', '')
        
        shipment.save()
        
        logger.info(f'Shipment updated: {shipment.shipment_number} by {request.user}')
        messages.success(request, f'Shipment {shipment.shipment_number} updated successfully!')
        return redirect('shipments:shipment_detail', pk=shipment.pk)
    
    # Get companies for dropdowns
    customers = Company.objects.filter(company_type='customer', is_active=True)
    carriers = Company.objects.filter(company_type='carrier', is_active=True)
    all_companies = Company.objects.filter(is_active=True)
    
    context = {
        'shipment': shipment,
        'customers': customers,
        'carriers': carriers,
        'all_companies': all_companies,
        'shipment_types': Shipment.SHIPMENT_TYPE_CHOICES,
        'is_create': False,
    }
    return render(request, 'shipments/form.html', context)


@login_required
def shipment_delete(request, pk):
    """Delete shipment"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    if request.method == 'POST':
        shipment_number = shipment.shipment_number
        shipment.delete()
        logger.info(f'Shipment deleted: {shipment_number} by {request.user}')
        messages.success(request, f'Shipment {shipment_number} deleted successfully!')
        return redirect('shipments:shipment_list')
    
    context = {
        'shipment': shipment,
    }
    return render(request, 'shipments/confirm_delete.html', context)


@login_required
def document_upload(request, pk):
    """Upload document for shipment"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    if request.method == 'POST' and request.FILES.get('file'):
        document = Document(
            shipment=shipment,
            document_type=request.POST.get('document_type', 'other'),
            title=request.POST.get('title', 'Document'),
            file=request.FILES['file'],
            uploaded_by=request.user
        )
        document.save()
        logger.info(f'Document uploaded: {document.title} for shipment {shipment.shipment_number} by {request.user}')
        messages.success(request, 'Document uploaded successfully!')
    
    return redirect('shipments:shipment_detail', pk=pk)


@login_required
def document_download(request, doc_pk):
    """Download document"""
    document = get_object_or_404(Document, pk=doc_pk)
    response = HttpResponse(document.file, content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{document.file.name}"'
    return response


@login_required
def generate_bol(request, pk):
    """Generate Bill of Lading"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    # Generate BOL number
    bol_number = f"BOL-{datetime.now().year}-{shipment.id:05d}"
    
    context = {
        'shipment': shipment,
        'bol_number': bol_number,
        'containers': shipment.containers.all(),
        'today': datetime.now().strftime('%B %d, %Y'),
    }
    return render(request, 'documents/bill_of_lading.html', context)


@login_required
def generate_shipping_confirmation(request, pk):
    """Generate Shipping Confirmation document"""
    shipment = get_object_or_404(Shipment.objects.select_related(
        'order', 'order__supplier', 'order__receiver', 'carrier', 'customer', 'shipper', 'consignee'
    ), pk=pk)

    manifest_items = []
    if shipment.order:
        manifest_items = shipment.order.manifest_items.all()

    context = {
        'shipment': shipment,
        'manifest_items': manifest_items,
        'today': datetime.now().strftime('%m/%d/%Y'),
    }
    return render(request, 'documents/shipping_confirmation.html', context)


@login_required
def generate_packing_list(request, pk):
    """Generate Packing List document"""
    shipment = get_object_or_404(Shipment.objects.select_related(
        'order', 'order__supplier', 'order__receiver', 'customer'
    ), pk=pk)

    manifest_items = []
    if shipment.order:
        manifest_items = shipment.order.manifest_items.all()

    context = {
        'shipment': shipment,
        'manifest_items': manifest_items,
        'today': datetime.now().strftime('%B %d, %Y'),
    }
    return render(request, 'documents/packing_list.html', context)


@login_required
def create_invoice(request, pk):
    """Create or view invoice linked to this shipment"""
    from apps.invoicing.models import Invoice, InvoiceLineItem
    from datetime import date, timedelta
    from django.db import transaction

    shipment = get_object_or_404(Shipment.objects.select_related('order', 'customer'), pk=pk)

    # If invoice already exists for this shipment, redirect to it
    existing = Invoice.objects.filter(shipment=shipment).first()
    if existing:
        messages.info(request, f'Invoice {existing.invoice_number} already exists for this shipment.')
        return redirect('invoicing:invoice_detail', pk=existing.pk)

    if request.method == 'POST':
        # Calculate subtotal from manifest items if linked to an order
        subtotal = Decimal('0.00')
        if shipment.order:
            for item in shipment.order.manifest_items.all():
                subtotal += (item.weight * item.sell_price)
        else:
            subtotal = shipment.revenue
            
        due_date = date.today() + timedelta(days=30)

        # Use transaction to ensure atomicity
        try:
            with transaction.atomic():
                # Generate invoice number first
                invoice_number = Invoice.generate_invoice_number()
                
                invoice = Invoice.objects.create(
                    customer=shipment.customer,
                    shipment=shipment,
                    order=shipment.order,
                    invoice_number=invoice_number,
                    invoice_date=date.today(),
                    due_date=due_date,
                    subtotal=subtotal,
                    total=subtotal,
                    status='draft',
                    payment_instructions=request.POST.get('payment_instructions', ''),
                    tax_details=request.POST.get('tax_details', ''),
                    notes=request.POST.get('notes', ''),
                    file_name=request.POST.get('file_name', ''),
                    terms=request.POST.get('terms', 'Net 30 days'),
                    created_by=request.user,
                    tenant=request.user.tenant,
                )
                
                # Add manifest items as invoice line items if available
                if shipment.order:
                    include_descriptions = request.POST.get('include_descriptions') == 'on'
                    for item in shipment.order.manifest_items.all():
                        description = item.material
                        if include_descriptions:
                            extra_desc = request.POST.get(f'desc_{item.id}', '').strip()
                            if extra_desc:
                                description = f"{description} - {extra_desc}"
                                
                        try:
                            InvoiceLineItem.objects.create(
                                invoice=invoice,
                                description=description,
                                quantity=item.weight,
                                unit_price=item.sell_price,
                                total=item.weight * item.sell_price,
                            )
                        except Exception as e:
                            pass
        except Exception as e:
            messages.error(request, f'Error creating invoice: {str(e)}')
            return redirect('shipments:create_invoice', pk=pk)

        messages.success(request, f'Invoice {invoice.invoice_number} created successfully!')
        return redirect('invoicing:invoice_list')

    # Show confirmation page
    from datetime import date
    # Generate preview number (but don't save)
    try:
        next_invoice_number = Invoice.generate_invoice_number()
    except:
        next_invoice_number = "Generating..."
    
    context = {
        'shipment': shipment,
        'existing_invoices': Invoice.objects.filter(shipment=shipment),
        'next_invoice_number': next_invoice_number,
        'today': date.today(),
    }
    return render(request, 'shipments/confirm_invoice.html', context)



def public_tracking(request, tracking_number):
    """Public tracking page (no login required)"""
    shipment = get_object_or_404(Shipment, tracking_number=tracking_number)
    
    context = {
        'shipment': shipment,
        'milestones': shipment.milestones.all(),
    }
    return render(request, 'shipments/public_tracking.html', context)


@login_required
def update_status(request, pk):
    """Update shipment status via POST"""
    shipment = get_object_or_404(Shipment, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        valid_statuses = [s[0] for s in Shipment.STATUS_CHOICES]
        if new_status and new_status in valid_statuses:
            old_status = shipment.get_status_display()
            shipment.status = new_status
            shipment.save()
            ShipmentMilestone.objects.create(
                shipment=shipment,
                status=f'Status changed to {shipment.get_status_display()}',
                notes=f'Status updated from {old_status}',
                created_by=request.user
            )
            logger.info(f'Shipment {shipment.shipment_number} status: {old_status} → {shipment.get_status_display()} by {request.user}')
            messages.success(request, f'Status updated to {shipment.get_status_display()}.')
        else:
            logger.warning(f'Invalid status update attempted on shipment {pk} by {request.user}: {new_status}')
            messages.error(request, 'Invalid status.')
    return redirect('shipments:shipment_detail', pk=pk)


# Import models at the end to avoid circular imports
from django.db import models
