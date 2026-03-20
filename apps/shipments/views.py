"""
Shipments Views - Main views for shipment management
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Shipment, Container, ShipmentMilestone, Document
from apps.accounts.models import Company, CustomUser
from apps.invoicing.models import Invoice
from apps.orders.models import Order, PackagingType
from apps.inventory.models import Warehouse, InventoryItem
from apps.orders.models import Tag, ShippingTerm
from apps.accounts.utils import filter_by_user_company, check_company_access
import logging

logger = logging.getLogger('apps.shipments')


def _get_tracking_shipment_for_user(user, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    if user.tenant and shipment.tenant_id != user.tenant_id:
        raise PermissionDenied("You do not have access to this shipment.")
    return shipment


def _reverse_geocode_location(latitude, longitude):
    """
    Resolve GPS coordinates into a short human-readable place label.
    Falls back to raw coordinates if the reverse geocoding service is unavailable.
    """
    fallback = f"Lat {latitude:.5f}, Lng {longitude:.5f}"
    try:
        query = urlencode({
            'lat': f'{latitude}',
            'lon': f'{longitude}',
            'format': 'jsonv2',
            'zoom': 10,
            'addressdetails': 1,
        })
        url = f"{settings.MAP_REVERSE_GEOCODING_API_URL}?{query}"
        request = Request(url, headers={
            'User-Agent': 'FreightPro/1.0 (live-tracking)',
            'Accept': 'application/json',
        })
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode('utf-8'))

        address = payload.get('address', {})
        city = (
            address.get('city')
            or address.get('town')
            or address.get('village')
            or address.get('county')
            or address.get('state_district')
        )
        state = address.get('state')
        country = address.get('country')

        parts = [part for part in [city, state, country] if part]
        if parts:
            return ', '.join(parts[:3])

        display_name = payload.get('display_name', fallback)
        return ', '.join(display_name.split(',')[:3]).strip() or fallback
    except Exception as exc:
        logger.debug(f"Reverse geocoding failed for {latitude}, {longitude}: {exc}")
        return fallback



@login_required
def dashboard(request):
    """Main dashboard view"""
    # Get date ranges
    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_6_months = today - timedelta(days=180)
    selected_chart_month = request.GET.get('chart_month', today.strftime('%Y-%m'))

    try:
        chart_month_start = datetime.strptime(f"{selected_chart_month}-01", "%Y-%m-%d").date()
    except ValueError:
        chart_month_start = month_start
        selected_chart_month = chart_month_start.strftime('%Y-%m')

    if chart_month_start.month == 12:
        chart_month_end = chart_month_start.replace(year=chart_month_start.year + 1, month=1)
    else:
        chart_month_end = chart_month_start.replace(month=chart_month_start.month + 1)
    
    # Base queryset filtered by user's company
    base_qs = filter_by_user_company(Shipment.objects.all(), request.user)
    invoice_qs = filter_by_user_company(Invoice.objects.all(), request.user)
    order_qs = filter_by_user_company(Order.objects.all(), request.user, company_field='receiver')
    
    # Stat cards
    active_shipments = base_qs.filter(
        status__in=['pending', 'dispatched', 'in_transit', 'approved', 'invoiced']
    ).count()
    
    monthly_revenue = base_qs.filter(
        status='delivered'
    ).filter(
        Q(actual_delivery_date__gte=month_start) | 
        Q(actual_delivery_date__isnull=True, estimated_delivery_date__gte=month_start)
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
            status='delivered'
        ).filter(
            Q(actual_delivery_date__gte=month_start_date, actual_delivery_date__lte=month_end_date) |
            Q(actual_delivery_date__isnull=True, estimated_delivery_date__gte=month_start_date, estimated_delivery_date__lte=month_end_date)
        ).aggregate(total=Sum('revenue'))['total'] or 0
        
        months.append(month_date.strftime('%b'))
        revenue_data.append(float(month_revenue))
    
    # Shipment status distribution - dynamic for all choices
    status_counts = base_qs.filter(
        created_at__date__gte=chart_month_start,
        created_at__date__lt=chart_month_end,
    ).values('status').annotate(count=Count('id'))
    status_counts_dict = {item['status']: item['count'] for item in status_counts}
    
    status_data = []
    status_labels = []
    for code, label in Shipment.STATUS_CHOICES:
        status_data.append(status_counts_dict.get(code, 0))
        status_labels.append(label)

    # Order status distribution
    order_status_counts = order_qs.filter(
        created_at__date__gte=chart_month_start,
        created_at__date__lt=chart_month_end,
    ).values('status').annotate(count=Count('id'))
    order_status_counts_dict = {item['status']: item['count'] for item in order_status_counts}

    order_status_data = []
    order_status_labels = []
    for code, label in Order.STATUS_CHOICES:
        order_status_data.append(order_status_counts_dict.get(code, 0))
        order_status_labels.append(label)
    
    # Recent shipments
    recent_shipments = base_qs.select_related('customer').order_by('-created_at')[:10]

    chart_month_options = []
    option_month = today.replace(day=1)
    for _ in range(12):
        chart_month_options.append({
            'value': option_month.strftime('%Y-%m'),
            'label': option_month.strftime('%B %Y'),
        })
        if option_month.month == 1:
            option_month = option_month.replace(year=option_month.year - 1, month=12)
        else:
            option_month = option_month.replace(month=option_month.month - 1)
    
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
        'status_data': json.dumps(status_data),
        'status_labels': json.dumps(status_labels),
        'order_status_data': json.dumps(order_status_data),
        'order_status_labels': json.dumps(order_status_labels),
        'selected_chart_month': selected_chart_month,
        'chart_month_options': chart_month_options,
        
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
    
    # Filter parameters
    status = request.GET.get('status')
    shipment_type = request.GET.get('type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Debug logging
    logger.debug(f"Shipment list filters: search={search}, status={status}, type={shipment_type}, from={date_from}, to={date_to}")
    
    # Status filter
    if status and status != '':
        shipments = shipments.filter(status=status)
    
    # Type filter
    if shipment_type and shipment_type != '':
        shipments = shipments.filter(shipment_type=shipment_type)
    
    # Date range filter
    if date_from:
        shipments = shipments.filter(pickup_date__gte=date_from)
    if date_to:
        shipments = shipments.filter(pickup_date__lte=date_to)
    
    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    shipments = shipments.order_by(sort_by)
    
    # Final count after filters
    total_count = shipments.count()
    logger.debug(f"Total shipments after filtering: {total_count}")
    
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
        'users': CustomUser.objects.filter(tenant=request.user.tenant, is_active=True).order_by('first_name'),
        'map_data': json.dumps(map_data),
        'next_invoice_number': Invoice.generate_invoice_number(shipment) if hasattr(Invoice, 'generate_invoice_number') else "Generating...",
        'today': timezone.now().date(),
        'download_invoice_id': request.session.pop('download_invoice_id', None),
        'tracking_update_url': f"/shipments/{shipment.pk}/tracking/update/",
    }
    return render(request, 'shipments/detail.html', context)


@login_required
def shipment_tracking_mobile(request, pk):
    """Mobile-first page for drivers or staff to stream GPS updates."""
    shipment = _get_tracking_shipment_for_user(request.user, pk)
    context = {
        'shipment': shipment,
        'tracking_update_url': f"/shipments/{shipment.pk}/tracking/update/",
        'tracking_can_update': request.user.role != 'customer',
        'tracking_can_update_status': True,
    }
    return render(request, 'shipments/tracking_mobile.html', context)


@login_required
def shipment_tracking_update(request, pk):
    """Accept live GPS pings from the mobile tracking page."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    shipment = _get_tracking_shipment_for_user(request.user, pk)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)

    latitude = payload.get('latitude')
    longitude = payload.get('longitude')
    status = payload.get('status')
    event = payload.get('event')
    is_customer = request.user.role == 'customer'

    milestone_status = None
    milestone_notes = ''

    if status in dict(Shipment.STATUS_CHOICES) and shipment.status != status:
        previous_status = shipment.get_status_display()
        shipment.status = status
        milestone_status = f"Status changed to {shipment.get_status_display()}"
        milestone_notes = f"Updated by {request.user.username} from {previous_status}"
        if status == 'delivered' and not shipment.actual_delivery_date:
            shipment.actual_delivery_date = timezone.now().date()

    if is_customer:
        shipment.save(update_fields=['status', 'actual_delivery_date', 'updated_at'])
        if milestone_status:
            ShipmentMilestone.objects.create(
                shipment=shipment,
                status=milestone_status,
                location=shipment.current_location_display,
                latitude=shipment.current_latitude,
                longitude=shipment.current_longitude,
                notes=milestone_notes,
                created_by=request.user,
            )
        return JsonResponse({
            'ok': True,
            'shipment_number': shipment.shipment_number,
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'current_location': shipment.current_location_display,
            'last_updated': shipment.last_location_updated_at.isoformat() if shipment.last_location_updated_at else None,
            'tracking_active': shipment.tracking_active,
        })

    if latitude in (None, '') or longitude in (None, ''):
        return JsonResponse({'error': 'Latitude and longitude are required'}, status=400)

    try:
        shipment.current_latitude = Decimal(str(latitude))
        shipment.current_longitude = Decimal(str(longitude))
    except Exception:
        return JsonResponse({'error': 'Invalid coordinates'}, status=400)

    resolved_location = _reverse_geocode_location(shipment.current_latitude, shipment.current_longitude)
    shipment.last_location_text = resolved_location
    shipment.last_location_updated_at = timezone.now()
    shipment.tracking_active = payload.get('tracking_active', True)
    if milestone_status and not milestone_notes:
        milestone_notes = 'Live update received'
    elif event == 'tracking_started':
        milestone_status = 'Live tracking started'
        milestone_notes = 'Driver/mobile location sharing started'
    elif event == 'tracking_stopped':
        shipment.tracking_active = False
        milestone_status = 'Live tracking stopped'
        milestone_notes = 'Driver/mobile location sharing stopped'

    shipment.save(update_fields=[
        'current_latitude',
        'current_longitude',
        'last_location_text',
        'last_location_updated_at',
        'tracking_active',
        'status',
        'actual_delivery_date',
        'updated_at',
    ])

    if milestone_status:
        ShipmentMilestone.objects.create(
            shipment=shipment,
            status=milestone_status,
            location=resolved_location,
            latitude=shipment.current_latitude,
            longitude=shipment.current_longitude,
            notes=milestone_notes,
            created_by=request.user,
        )

    return JsonResponse({
        'ok': True,
        'shipment_number': shipment.shipment_number,
        'status': shipment.status,
        'status_display': shipment.get_status_display(),
        'current_location': shipment.current_location_display,
        'last_updated': shipment.last_location_updated_at.isoformat() if shipment.last_location_updated_at else None,
        'tracking_active': shipment.tracking_active,
    })


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
    user_tenant = request.user.tenant

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
            status='pending',
            
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

            # Tracking
            vehicle_number=request.POST.get('vehicle_number', ''),
            driver_name=request.POST.get('driver_name', ''),
            driver_phone=request.POST.get('driver_phone', ''),
            
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
            notes=f'Shipment created in system. Driver: {shipment.driver_name or "Not assigned"} | Vehicle: {shipment.vehicle_number or "Not assigned"}',
            created_by=request.user
        )
        
        logger.info(f'Shipment created: {shipment.shipment_number} for {shipment.customer} by {request.user}')
        messages.success(request, f'Shipment {shipment.shipment_number} created successfully!')
        return redirect('shipments:shipment_detail', pk=shipment.pk)
    
    # Match Order create dropdown sources exactly so the supplier list is identical.
    all_companies = Company.plain_objects.all().order_by('name')
    suppliers = all_companies
    customers = all_companies.filter(company_type='customer')
    carriers = all_companies.filter(company_type='carrier')
    warehouses = Warehouse.plain_objects.filter(tenant=user_tenant).order_by('name')
    inventory_items = InventoryItem.plain_objects.all()
    tags = Tag.plain_objects.filter(tenant=user_tenant).order_by('name')
    shipping_terms = ShippingTerm.plain_objects.filter(tenant=user_tenant).order_by('name')
    representatives = CustomUser.objects.filter(tenant=user_tenant, is_active=True).order_by('first_name', 'username')
    packaging_types = PackagingType.objects.all().order_by('name')
    
    context = {
        'order': order,
        'suppliers': suppliers,
        'customers': customers,
        'carriers': carriers,
        'all_companies': all_companies,
        'warehouses': warehouses,
        'inventory_items': inventory_items,
        'tags': tags,
        'shipping_terms': shipping_terms,
        'representatives': representatives,
        'packaging_types': packaging_types,
        'shipment_types': Shipment.SHIPMENT_TYPE_CHOICES,
        'default_pieces': int(order.total_pieces) if order.total_pieces else 1,
        'default_weight': order.total_manifest_weight if order.total_manifest_weight else 0,
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

        # Tracking
        shipment.vehicle_number = request.POST.get('vehicle_number', '')
        shipment.driver_name = request.POST.get('driver_name', '')
        shipment.driver_phone = request.POST.get('driver_phone', '')
        
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
        
        # Auto-set actual_delivery_date if status is delivered
        if shipment.status == 'delivered' and not shipment.actual_delivery_date:
            shipment.actual_delivery_date = timezone.now().date()
            
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
def document_delete(request, doc_pk):
    """Delete document"""
    document = get_object_or_404(Document, pk=doc_pk)
    shipment_pk = document.shipment.pk
    
    # Check if user has access (e.g. uploaded it or is admin/manager)
    # Simple check for now based on previous patterns
    if request.method == 'POST':
        title = document.title
        document.delete()
        logger.info(f'Document deleted: {title} by {request.user}')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success'})
        messages.success(request, 'Document deleted successfully!')
    
    return redirect('shipments:shipment_detail', pk=shipment_pk)


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
def generate_bol_pdf(request, pk):
    """Generate professional Bill of Lading PDF using ReportLab with custom form data"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from io import BytesIO

    shipment = get_object_or_404(Shipment.objects.select_related(
        'carrier', 'customer', 'shipper', 'consignee'
    ), pk=pk)
    
    # Get form data
    file_name = request.POST.get('file_name', f"{shipment.shipment_number}_BoL.pdf")
    if not file_name.endswith('.pdf'):
        file_name += '.pdf'
    
    is_blind = request.POST.get('blind_shipment') == 'on'
    carrier_name = request.POST.get('carrier_name', shipment.carrier.name if shipment.carrier else '')
    trailer_number = request.POST.get('trailer_number', '')
    seal_number = request.POST.get('seal_number', '')
    custom_instructions = request.POST.get('instructions', shipment.special_instructions or '')
    
    bol_number = f"BOL-{datetime.now().year}-{shipment.id:05d}"
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor('#2a4d8f')
    dark_gray = colors.HexColor('#1e293b')
    light_gray = colors.HexColor('#f8fafc')
    
    # Custom Styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, textColor=dark_gray, fontName='Helvetica-Bold', alignment=TA_CENTER, leading=24)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748b'), fontName='Helvetica-Bold', leading=10, textTransform='uppercase')
    normal_style = ParagraphStyle('Normal2', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica', leading=13)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica-Bold', leading=13)
    th_style = ParagraphStyle('TH', parent=styles['Normal'], fontSize=9, textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_LEFT)
    td_style = ParagraphStyle('TD', parent=styles['Normal'], fontSize=9, textColor=dark_gray, fontName='Helvetica')
    
    elements = []

    # ─── HEADER ───
    shipment_info = [
        Paragraph("<b>BILL OF LADING</b>", title_style),
        Spacer(1, 4*mm),
        Paragraph(f"<b>BOL #:</b> {bol_number}", normal_style),
        Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}", normal_style),
        Paragraph(f"<b>Shipment #:</b> {shipment.shipment_number}", normal_style),
    ]

    company_lines = [
        Paragraph("FreightPro", ParagraphStyle('CompName', parent=bold_style, fontSize=18, textColor=primary_color)),
        Paragraph("Logistics & Freight Services", normal_style),
        Paragraph("123 Logistics Way, Chicago, IL 60601", normal_style),
        Paragraph("Phone: (555) 123-4567", normal_style),
    ]

    header_table = Table([[company_lines, shipment_info]], colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elements.append(header_table)
    elements.append(Spacer(1, 8*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.grey, spaceBefore=0, spaceAfter=8*mm))

    # ─── PARTIES ───
    shipper_box = [Paragraph("SHIPPER", label_style), Spacer(1, 1*mm)]
    if is_blind:
        shipper_box.append(Paragraph("CONFIDENTIAL", bold_style))
        shipper_box.append(Paragraph("Shipper information withheld", normal_style))
    else:
        s = shipment.shipper or shipment.customer
        if s:
            shipper_box.append(Paragraph(s.name, bold_style))
            shipper_box.append(Paragraph(shipment.origin_address or "", normal_style))
            shipper_box.append(Paragraph(f"{shipment.origin_city}, {shipment.origin_state} {shipment.origin_postal_code}", normal_style))
            shipper_box.append(Paragraph(shipment.origin_country or "", normal_style))

    consignee_box = [Paragraph("CONSIGNEE / NOTIFY PARTY", label_style), Spacer(1, 1*mm)]
    c = shipment.consignee
    if c:
        consignee_box.append(Paragraph(c.name, bold_style))
        consignee_box.append(Paragraph(shipment.destination_address or "", normal_style))
        consignee_box.append(Paragraph(f"{shipment.destination_city}, {shipment.destination_state} {shipment.destination_postal_code}", normal_style))
        consignee_box.append(Paragraph(shipment.destination_country or "", normal_style))
    else:
        consignee_box.append(Paragraph("TO BE NOTIFIED", bold_style))

    carrier_box = [Paragraph("CARRIER", label_style), Spacer(1, 1*mm)]
    carrier_final = carrier_name or (shipment.carrier.name if shipment.carrier else "TO BE ASSIGNED")
    carrier_box.append(Paragraph(carrier_final, bold_style))
    if trailer_number: carrier_box.append(Paragraph(f"Trailer #: {trailer_number}", normal_style))
    if seal_number: carrier_box.append(Paragraph(f"Seal #: {seal_number}", normal_style))

    parties_table = Table([[shipper_box, consignee_box, carrier_box]], colWidths=[60*mm, 60*mm, 60*mm])
    parties_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(parties_table)
    elements.append(Spacer(1, 6*mm))

    # ─── CARGO DETAILS ───
    elements.append(Paragraph("CARGO DETAILS", label_style))
    elements.append(Spacer(1, 2*mm))
    
    cargo_data = [[Paragraph("CONTAINER #", th_style), Paragraph("SIZE", th_style), Paragraph("PIECES", th_style), Paragraph("WEIGHT (KG)", th_style), Paragraph("DESCRIPTION", th_style)]]
    
    containers = shipment.containers.all()
    if containers:
        for cont in containers:
            cargo_data.append([
                Paragraph(cont.container_number, td_style),
                Paragraph(cont.get_size_display(), td_style),
                Paragraph(str(shipment.number_of_pieces or "-"), td_style),
                Paragraph(f"{cont.weight:,.0f}" if cont.weight else "-", td_style),
                Paragraph(shipment.commodity_description or "Freight", td_style)
            ])
    else:
        cargo_data.append([
            Paragraph("N/A", td_style),
            Paragraph("N/A", td_style),
            Paragraph(str(shipment.number_of_pieces or "-"), td_style),
            Paragraph(f"{shipment.total_weight:,.0f}" if shipment.total_weight else "-", td_style),
            Paragraph(shipment.commodity_description or "Freight", td_style)
        ])

    cargo_table = Table(cargo_data, colWidths=[35*mm, 25*mm, 20*mm, 30*mm, 70*mm])
    cargo_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(cargo_table)
    elements.append(Spacer(1, 10*mm))

    # ─── INSTRUCTIONS ───
    if custom_instructions:
        elements.append(Paragraph("SPECIAL INSTRUCTIONS", label_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(custom_instructions, normal_style))
        elements.append(Spacer(1, 8*mm))

    # ─── SIGNATURES ───
    sig_data = [
        [Paragraph("SHIPPER SIGNATURE", label_style), Paragraph("CARRIER SIGNATURE", label_style), Paragraph("CONSIGNEE SIGNATURE", label_style)],
        [Spacer(1, 15*mm), Spacer(1, 15*mm), Spacer(1, 15*mm)],
        [Paragraph("Date: _______________", normal_style), Paragraph("Date: _______________", normal_style), Paragraph("Date: _______________", normal_style)]
    ]
    sig_table = Table(sig_data, colWidths=[60*mm, 60*mm, 60*mm])
    sig_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,0), 0.5, colors.grey),
        ('GRID', (0,1), (-1,1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(sig_table)
    
    # ─── TERMS ───
    elements.append(Spacer(1, 10*mm))
    elements.append(Paragraph("TERMS AND CONDITIONS", label_style))
    terms = """This Bill of Lading is issued subject to the terms and conditions of the carrier's tariff and applicable laws. The shipper certifies that the particulars furnished are correct and agrees to indemnify the carrier against all loss, damage, and expense arising from any inaccuracy. The carrier shall not be liable for any loss or damage unless a written claim is filed within 9 months from the date of delivery."""
    elements.append(Paragraph(terms, ParagraphStyle('Terms', parent=styles['Normal'], fontSize=7, leading=9, textColor=colors.grey)))

    doc.build(elements)
    
    pdf = buffer.getvalue()
    buffer.close()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    response.write(pdf)
    return response


@login_required
def generate_shipping_confirmation(request, pk):
    """Generate Shipping Confirmation document (HTML version)"""
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
def generate_shipping_confirmation_pdf(request, pk):
    """Generate professional Shipping Confirmation PDF using ReportLab"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from io import BytesIO

    shipment = get_object_or_404(Shipment.objects.select_related(
        'order', 'order__supplier', 'order__receiver', 'carrier', 'customer', 'shipper', 'consignee'
    ), pk=pk)
    
    # Get form data
    file_name = request.POST.get('file_name', f"{shipment.shipment_number}_SHIP.pdf")
    if not file_name.endswith('.pdf'):
        file_name += '.pdf'
    
    user_contact_id = request.POST.get('user_contact')
    user_contact = None
    if user_contact_id:
        try:
            user_contact = CustomUser.objects.get(pk=user_contact_id)
        except CustomUser.DoesNotExist:
            pass
            
    scale_required = request.POST.get('scale_required') == 'on'
    custom_instructions = request.POST.get('instructions', '')

    manifest_items = []
    if shipment.order:
        manifest_items = list(shipment.order.manifest_items.all())

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor('#2a4d8f')
    light_gray = colors.HexColor('#f8fafc')
    dark_gray = colors.HexColor('#1e293b')
    header_bg = colors.HexColor('#2a4d8f')

    # Custom Styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, textColor=dark_gray, fontName='Helvetica-Bold', alignment=TA_RIGHT, leading=26)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748b'), fontName='Helvetica-Bold', leading=10, textTransform='uppercase')
    normal_style = ParagraphStyle('Normal2', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica', leading=13)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica-Bold', leading=13)
    right_style = ParagraphStyle('Right', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica', alignment=TA_RIGHT, leading=13)
    company_name_style = ParagraphStyle('Company', parent=styles['Normal'], fontSize=18, textColor=primary_color, fontName='Helvetica-Bold', leading=22)
    th_style = ParagraphStyle('TH', parent=styles['Normal'], fontSize=9, textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_CENTER)
    td_style = ParagraphStyle('TD', parent=styles['Normal'], fontSize=9, textColor=dark_gray, fontName='Helvetica')
    td_center = ParagraphStyle('TDC', parent=styles['Normal'], fontSize=9, textColor=dark_gray, fontName='Helvetica', alignment=TA_CENTER)

    elements = []

    # ─── HEADER ───
    shipment_info = [
        Paragraph("SHIPPING CONFIRMATION", title_style),
        Spacer(1, 2*mm),
        Paragraph(f"<b>SHIPMENT ID:</b> {shipment.shipment_number}", right_style),
        Paragraph(f"<b>ORDER ID:</b> {shipment.order.order_number if shipment.order else 'N/A'}", right_style),
        Paragraph(f"<b>DATE:</b> {datetime.now().strftime('%m/%d/%Y')} (ET)", right_style),
    ]

    company_lines = [Paragraph("FreightPro Inc.", company_name_style)]
    if shipment.order and shipment.order.supplier:
        s = shipment.order.supplier
        company_lines.append(Paragraph(s.address_line1 or "", normal_style))
        company_lines.append(Paragraph(f"{s.city}, {s.state} {s.postal_code}, {s.country}", normal_style))

    header_table = Table([[company_lines, shipment_info]], colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elements.append(header_table)
    elements.append(Spacer(1, 10*mm))

    # ─── SHIPPER / RECEIVER ───
    shipper_box = [Paragraph("SHIPPER", label_style)]
    s = shipment.shipper or (shipment.order.supplier if shipment.order else None)
    if s:
        shipper_box.append(Paragraph(s.name, bold_style))
        shipper_box.append(Paragraph(s.address_line1 or "", normal_style))
        shipper_box.append(Paragraph(f"{s.city}, {s.state} {s.postal_code}, {s.country}", normal_style))
        if s.phone: shipper_box.append(Paragraph(f"Phone: {s.phone}", normal_style))
    
    if shipment.pickup_date:
        shipper_box.append(Spacer(1, 2*mm))
        shipper_box.append(Paragraph(f"<b>Pickup Date:</b> {shipment.pickup_date.strftime('%m/%d/%Y')}", normal_style))

    receiver_box = [Paragraph("RECEIVER", label_style)]
    r = shipment.consignee or (shipment.order.receiver if shipment.order else None)
    if r:
        receiver_box.append(Paragraph(r.name, bold_style))
        receiver_box.append(Paragraph(shipment.destination_address or "", normal_style))
        receiver_box.append(Paragraph(f"{r.city}, {r.state} {r.postal_code}, {r.country}", normal_style))
        if r.phone: receiver_box.append(Paragraph(f"Phone: {r.phone}", normal_style))

    if shipment.estimated_delivery_date:
        receiver_box.append(Spacer(1, 2*mm))
        receiver_box.append(Paragraph(f"<b>Delivery Date:</b> {shipment.estimated_delivery_date.strftime('%m/%d/%Y')}", normal_style))

    parties_table = Table([[shipper_box, receiver_box]], colWidths=[90*mm, 90*mm])
    parties_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(parties_table)
    elements.append(Spacer(1, 6*mm))

    # ─── ORDERED BY / CARRIER ───
    ordered_by = [
        Paragraph("ORDERED BY", label_style),
        Paragraph(shipment.customer.name if shipment.customer else "N/A", bold_style),
        Paragraph(shipment.customer.email if shipment.customer and shipment.customer.email else "", normal_style),
    ]
    if user_contact:
        ordered_by.append(Spacer(1, 2*mm))
        ordered_by.append(Paragraph(f"<b>Contact:</b> {user_contact.get_full_name() or user_contact.username}", normal_style))

    carrier_info = [
        Paragraph("CARRIER / RATE", label_style),
        Paragraph(shipment.carrier.name if shipment.carrier else "TBD", bold_style),
        Paragraph(f"Rate: ${shipment.quoted_amount:,.2f}" if shipment.quoted_amount else "Rate: TBD", normal_style),
    ]

    middle_table = Table([[ordered_by, carrier_info]], colWidths=[90*mm, 90*mm])
    middle_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(middle_table)
    elements.append(Spacer(1, 6*mm))

    # ─── MANIFEST ITEMS ───
    data = [[Paragraph("ITEM DESCRIPTION", th_style), Paragraph("PACKAGING", th_style), Paragraph("WEIGHT", th_style)]]
    for item in manifest_items:
        data.append([
            Paragraph(item.material, td_style),
            Paragraph(item.packaging or "-", td_center),
            Paragraph(f"{item.weight:,.0f} {item.weight_unit}", td_center)
        ])
    
    # Fill empty rows to maintain structure
    while len(data) < 7:
        data.append(["", "", ""])

    data.append([
        Paragraph("<b>TOTALS</b>", ParagraphStyle('RightB', parent=td_style, alignment=TA_RIGHT)),
        "",
        Paragraph(f"<b>{shipment.total_weight:,.0f} kg</b>", td_center)
    ])

    items_table = Table(data, colWidths=[90*mm, 50*mm, 40*mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), header_bg),
        ('GRID', (0,0), (-1,-2), 0.5, colors.grey),
        ('BOX', (0,-1), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 6*mm))

    # ─── INSTRUCTIONS ───
    instructions_box = [
        Paragraph("INSTRUCTIONS", label_style),
        Paragraph(custom_instructions or shipment.special_instructions or "None", normal_style)
    ]
    scale_box = [
        Paragraph("SCALE REQUIRED", label_style),
        Paragraph("YES" if scale_required else "NO", bold_style if scale_required else normal_style)
    ]

    footer_row = Table([[instructions_box, scale_box]], colWidths=[130*mm, 50*mm])
    footer_row.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(footer_row)

    elements.append(Spacer(1, 15*mm))
    elements.append(Paragraph("Generated by FreightPro", ParagraphStyle('Tiny', fontSize=7, textColor=colors.grey, alignment=TA_RIGHT)))

    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    return response


@login_required
def generate_packing_list(request, pk):
    """Generate Packing List document (HTML version)"""
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
def generate_packing_list_pdf(request, pk):
    """Generate professional Packing List PDF using ReportLab with dynamic items"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from io import BytesIO

    shipment = get_object_or_404(Shipment.objects.select_related(
        'customer', 'order', 'order__supplier', 'order__receiver'
    ), pk=pk)
    
    # Get form data
    file_name = request.POST.get('file_name', f"{shipment.shipment_number}_PACKING_LIST.pdf")
    if not file_name.endswith('.pdf'):
        file_name += '.pdf'
    
    delivery_number = request.POST.get('delivery_number', '')
    doc_date = request.POST.get('date', datetime.now().strftime('%Y-%m-%d'))
    unit = request.POST.get('unit', 'lbs')
    
    # Process dynamic items
    items = request.POST.getlist('item[]')
    gross_weights = request.POST.getlist('gross[]')
    tare_weights = request.POST.getlist('tare[]')
    packagings = request.POST.getlist('packaging[]')
    
    manifest_data = []
    total_gross = 0
    total_tare = 0
    total_net = 0
    
    for i in range(len(items)):
        if not items[i]: continue
        
        gross = float(gross_weights[i] or 0)
        tare = float(tare_weights[i] or 0)
        net = gross - tare
        
        manifest_data.append({
            'item': items[i],
            'gross': gross,
            'tare': tare,
            'net': net,
            'packaging': packagings[i]
        })
        
        total_gross += gross
        total_tare += tare
        total_net += net
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor('#2a4d8f')
    dark_gray = colors.HexColor('#1e293b')
    
    # Custom Styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, textColor=dark_gray, fontName='Helvetica-Bold', alignment=TA_CENTER, leading=24)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748b'), fontName='Helvetica-Bold', leading=10, textTransform='uppercase')
    normal_style = ParagraphStyle('Normal2', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica', leading=13)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, textColor=dark_gray, fontName='Helvetica-Bold', leading=13)
    th_style = ParagraphStyle('TH', parent=styles['Normal'], fontSize=9, textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_LEFT)
    td_style = ParagraphStyle('TD', parent=styles['Normal'], fontSize=9, textColor=dark_gray, fontName='Helvetica')
    td_center = ParagraphStyle('TDC', parent=styles['Normal'], fontSize=9, textColor=dark_gray, fontName='Helvetica', alignment=TA_CENTER)
    
    elements = []

    # ─── HEADER ───
    shipment_info = [
        Paragraph("<b>PACKING LIST</b>", title_style),
        Spacer(1, 4*mm),
        Paragraph(f"<b>Delivery #:</b> {delivery_number or 'N/A'}", normal_style),
        Paragraph(f"<b>Date:</b> {doc_date}", normal_style),
        Paragraph(f"<b>Shipment #:</b> {shipment.shipment_number}", normal_style),
    ]

    company_lines = [
        Paragraph("FreightPro", ParagraphStyle('CompName', parent=bold_style, fontSize=18, textColor=primary_color)),
        Paragraph("Logistics & Freight Services", normal_style),
        Paragraph("123 Logistics Way, Chicago, IL 60601", normal_style),
    ]

    header_table = Table([[company_lines, shipment_info]], colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elements.append(header_table)
    elements.append(Spacer(1, 8*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.grey, spaceBefore=0, spaceAfter=8*mm))

    # ─── PARTIES ───
    shipper_box = [Paragraph("SHIPPER", label_style), Spacer(1, 1*mm)]
    s = shipment.shipper or (shipment.order.supplier if shipment.order else None)
    if s:
        shipper_box.append(Paragraph(s.name, bold_style))
        shipper_box.append(Paragraph(shipment.origin_address or "", normal_style))
        shipper_box.append(Paragraph(f"{shipment.origin_city}, {shipment.origin_state} {shipment.origin_postal_code}", normal_style))

    consignee_box = [Paragraph("CONSIGNEE", label_style), Spacer(1, 1*mm)]
    c = shipment.consignee or (shipment.order.receiver if shipment.order else None)
    if c:
        consignee_box.append(Paragraph(c.name, bold_style))
        consignee_box.append(Paragraph(shipment.destination_address or "", normal_style))
        consignee_box.append(Paragraph(f"{shipment.destination_city}, {shipment.destination_state} {shipment.destination_postal_code}", normal_style))

    parties_table = Table([[shipper_box, consignee_box]], colWidths=[90*mm, 90*mm])
    parties_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(parties_table)
    elements.append(Spacer(1, 10*mm))

    # ─── ITEM TABLE ───
    cargo_data = [[
        Paragraph("#", th_style), 
        Paragraph("ITEM", th_style), 
        Paragraph(f"GROSS ({unit})", th_style), 
        Paragraph(f"TARE ({unit})", th_style), 
        Paragraph(f"NET ({unit})", th_style),
        Paragraph("PACKAGING", th_style)
    ]]
    
    for idx, item in enumerate(manifest_data, 1):
        cargo_data.append([
            Paragraph(str(idx), td_style),
            Paragraph(item['item'], td_style),
            Paragraph(f"{item['gross']:,.1f}", td_style),
            Paragraph(f"{item['tare']:,.1f}", td_style),
            Paragraph(f"{item['net']:,.1f}", td_style),
            Paragraph(item['packaging'], td_style)
        ])
        
    # Totals row
    cargo_data.append([
        "",
        Paragraph("<b>TOTALS</b>", ParagraphStyle('tot', parent=td_style, alignment=TA_RIGHT)),
        Paragraph(f"<b>{total_gross:,.1f}</b>", td_style),
        Paragraph(f"<b>{total_tare:,.1f}</b>", td_style),
        Paragraph(f"<b>{total_net:,.1f}</b>", td_style),
        ""
    ])

    cargo_table = Table(cargo_data, colWidths=[10*mm, 60*mm, 25*mm, 25*mm, 25*mm, 35*mm])
    cargo_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('GRID', (0,0), (-1,-2), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(cargo_table)
    
    # Signature
    elements.append(Spacer(1, 20*mm))
    sig_line = [
        Paragraph("_________________________", normal_style),
        Paragraph("Authorized Signature", label_style)
    ]
    sig_table = Table([[sig_line]], colWidths=[70*mm])
    sig_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'LEFT')]))
    elements.append(sig_table)

    doc.build(elements)
    
    pdf = buffer.getvalue()
    buffer.close()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    response.write(pdf)
    return response


@login_required
def create_invoice(request, pk):
    """Create or view invoice linked to this shipment"""
    from apps.invoicing.models import Invoice, InvoiceLineItem
    from datetime import date, timedelta
    from django.db import transaction

    shipment = get_object_or_404(Shipment.objects.select_related('order', 'customer'), pk=pk)

    existing = Invoice.objects.filter(shipment=shipment).first()

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
                if existing:
                    # Update existing invoice
                    invoice = existing
                    invoice.subtotal = subtotal
                    invoice.payment_instructions = request.POST.get('payment_instructions', invoice.payment_instructions)
                    invoice.tax_details = request.POST.get('tax_details', invoice.tax_details)
                    invoice.notes = request.POST.get('notes', invoice.notes)
                    invoice.tax_rate = Decimal(request.POST.get('tax_rate', '18.00'))
                    if request.POST.get('file_name'):
                        invoice.file_name = request.POST.get('file_name')
                    invoice.terms = request.POST.get('terms', invoice.terms)
                    
                    # Allow editing invoice number for existing invoices too
                    new_inv_num = request.POST.get('invoice_number')
                    if new_inv_num and new_inv_num != invoice.invoice_number:
                        if Invoice.objects.filter(invoice_number=new_inv_num).exists():
                             messages.error(request, f'Invoice number {new_inv_num} already exists. Please use a unique number.')
                             return redirect('shipments:shipment_detail', pk=pk)
                        invoice.invoice_number = new_inv_num
                    
                    invoice.save()
                    
                    # Clear and recreate line items for consistency
                    invoice.line_items.all().delete()
                else:
                    # Use provided invoice number or generate one
                    invoice_number = request.POST.get('invoice_number')
                    if not invoice_number:
                        invoice_number = Invoice.generate_invoice_number(shipment)
                    
                    # Check for duplicates if manually entered
                    if Invoice.objects.filter(invoice_number=invoice_number).exists():
                         messages.error(request, f'Invoice number {invoice_number} already exists. Please use a unique number.')
                         return redirect('shipments:shipment_detail', pk=pk)
                    
                    invoice = Invoice.objects.create(
                        customer=shipment.customer,
                        shipment=shipment,
                        order=shipment.order,
                        invoice_number=invoice_number,
                        invoice_date=date.today(),
                        due_date=due_date,
                        subtotal=subtotal,
                        status='draft',
                        payment_instructions=request.POST.get('payment_instructions', ''),
                        tax_details=request.POST.get('tax_details', ''),
                        notes=request.POST.get('notes', ''),
                        tax_rate=Decimal(request.POST.get('tax_rate', '18.00')),
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
            messages.error(request, f'Error processing invoice: {str(e)}')
            return redirect('shipments:shipment_detail', pk=pk)

        msg = f'Invoice {invoice.invoice_number} updated successfully!' if existing else f'Invoice {invoice.invoice_number} created successfully!'
        messages.success(request, msg)
        request.session['download_invoice_id'] = invoice.invoice_number
        return redirect('shipments:shipment_detail', pk=pk)

    # Show confirmation page
    from datetime import date
    # Generate preview number or use existing
    if existing:
        next_invoice_number = existing.invoice_number
    else:
        try:
            next_invoice_number = Invoice.generate_invoice_number(shipment)
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
            
            # Auto-set actual_delivery_date if status is delivered
            if shipment.status == 'delivered' and not shipment.actual_delivery_date:
                shipment.actual_delivery_date = timezone.now().date()
                
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
