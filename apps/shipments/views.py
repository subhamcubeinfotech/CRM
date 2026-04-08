"""
Shipments Views - Main views for shipment management
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q, F
from django.db import transaction, IntegrityError
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from decimal import InvalidOperation
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Shipment, Container, ShipmentMilestone, Document, ShipmentItem, ShipmentComment, ShipmentCommission
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


@login_required
@require_POST
def shipment_item_update_ajax(request, pk):
    item = get_object_or_404(
        ShipmentItem.objects.select_related('shipment'),
        pk=pk,
        shipment__tenant=request.user.tenant,
    )

    def _dec(name, default=None):
        raw = request.POST.get(name, None)
        if raw is None or raw == '':
            return default
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"Invalid {name}")

    def _int(name, default=None):
        raw = request.POST.get(name, None)
        if raw is None or raw == '':
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid {name}")

    try:
        item.weight = _dec('weight', item.weight)
        item.weight_unit = (request.POST.get('weight_unit') or item.weight_unit or 'lbs')[:10]

        item.gross_weight = _dec('gross_weight', None)
        item.gross_weight_unit = (request.POST.get('gross_weight_unit') or item.gross_weight_unit or item.weight_unit or 'lbs')[:10]

        item.tare_weight = _dec('tare_weight', None)
        item.tare_weight_unit = (request.POST.get('tare_weight_unit') or item.tare_weight_unit or item.weight_unit or 'lbs')[:10]

        item.packaging = (request.POST.get('packaging') or '')[:100]
        item.pieces = _int('pieces', None)
        item.is_palletized = request.POST.get('is_palletized') in ('1', 'true', 'on', 'yes')

        item.buy_price = _dec('buy_price', item.buy_price)
        item.sell_price = _dec('sell_price', item.sell_price)
        item.price_unit = (request.POST.get('price_unit') or item.price_unit or 'per lbs')[:20]

        item.save()
    except ValueError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return JsonResponse({
        'status': 'success',
        'item': {
            'id': item.id,
            'buy_price': f"{item.buy_price:.4f}",
            'sell_price': f"{item.sell_price:.4f}",
            'price_unit': item.price_unit,
            'weight': f"{item.weight:.2f}",
            'weight_unit': item.weight_unit,
            'gross_weight': f"{(item.gross_weight or 0):.2f}" if item.gross_weight is not None else '',
            'gross_weight_unit': item.gross_weight_unit or item.weight_unit,
            'tare_weight': f"{(item.tare_weight or 0):.2f}" if item.tare_weight is not None else '',
            'tare_weight_unit': item.tare_weight_unit or item.weight_unit,
            'pieces': item.pieces if item.pieces is not None else '',
            'packaging': item.packaging or '',
            'is_palletized': bool(item.is_palletized),
        }
    })


@login_required
@require_POST
def shipment_item_delete_ajax(request, pk):
    item = get_object_or_404(
        ShipmentItem.objects.select_related('shipment'),
        pk=pk,
        shipment__tenant=request.user.tenant,
    )
    item.delete()
    return JsonResponse({'status': 'success'})


@login_required
@transaction.atomic
def shipment_copy(request, pk):
    """Create a duplicate of an existing shipment and redirect to edit page"""
    original = get_object_or_404(Shipment, pk=pk)
    
    # Clone the shipment object
    new_shipment = get_object_or_404(Shipment, pk=pk)
    new_shipment.pk = None
    new_shipment.id = None
    new_shipment.shipment_number = None  # Model should auto-generate a new number
    new_shipment.status = 'pending'
    new_shipment.tracking_number = f"COPY-{original.tracking_number}" if original.tracking_number else ""
    new_shipment.created_at = timezone.now()
    new_shipment.updated_at = timezone.now()
    new_shipment.save()
    
    # Clone shipment items
    for item in original.items.all():
        ShipmentItem.objects.create(
            shipment=new_shipment,
            inventory_item=item.inventory_item,
            material_name=item.material_name,
            weight=item.weight,
            weight_unit=item.weight_unit,
            pieces=item.pieces,
            packaging=item.packaging,
            buy_price=item.buy_price,
            sell_price=item.sell_price,
        )
    
    messages.success(request, f"Shipment {original.shipment_number} copied successfully. You are now editing the copy.")
    return redirect('shipments:shipment_edit', pk=new_shipment.pk)


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


def _parse_items_from_post(post_data):
    """Parse multiple line items from the shipment form POST data"""
    items = []
    indices = set()
    for key in post_data.keys():
        if key.startswith('items_ui['):
            try:
                index = int(key.split('[')[1].split(']')[0])
                indices.add(index)
            except (IndexError, ValueError):
                continue
    
    for i in sorted(list(indices)):
        weight_val = post_data.get(f'items_ui[{i}][weight]', '0') or '0'
        pieces_val = post_data.get(f'items_ui[{i}][pieces]', '0')
        if not pieces_val.strip():
            pieces_val = '0'
        buy_val = post_data.get(f'items_ui[{i}][buy_price]', '0') or '0'
        sell_val = post_data.get(f'items_ui[{i}][sell_price]', '0') or '0'
        gross_val = post_data.get(f'items_ui[{i}][gross_weight]', '')
        tare_val = post_data.get(f'items_ui[{i}][tare_weight]', '')
        
        item = {
            'material_id': post_data.get(f'items_ui[{i}][material]'),
            'weight': float(weight_val),
            'weight_unit': post_data.get(f'items_ui[{i}][unit]', 'lbs'),
            'gross_weight': float(gross_val) if gross_val else None,
            'gross_weight_unit': post_data.get(f'items_ui[{i}][gross_unit]', 'lbs'),
            'tare_weight': float(tare_val) if tare_val else None,
            'tare_weight_unit': post_data.get(f'items_ui[{i}][tare_unit]', 'lbs'),
            'packaging': post_data.get(f'items_ui[{i}][packaging]', ''),
            'is_palletized': post_data.get(f'items_ui[{i}][palletized]') == 'on',
            'pieces': int(pieces_val),
            'buy_price': float(buy_val),
            'sell_price': float(sell_val),
            'price_unit': post_data.get(f'items_ui[{i}][buy_unit]', post_data.get(f'items_ui[{i}][price_unit]', 'per lbs')),
        }
        items.append(item)
    return items



@login_required
def dashboard(request):
    """Main dashboard view"""
    # Get date filters
    today = timezone.now().date()
    date_range = request.GET.get('date_range', 'this_month')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # Default range (this month)
    chart_start_date = today.replace(day=1)
    chart_end_date = today + timedelta(days=1)

    if date_range == 'last_7_days':
        chart_start_date = today - timedelta(days=7)
        chart_end_date = today + timedelta(days=1)
    elif date_range == 'last_30_days':
        chart_start_date = today - timedelta(days=30)
        chart_end_date = today + timedelta(days=1)
    elif date_range == 'last_month':
        # Get first and last day of previous month
        last_month_end = today.replace(day=1) - timedelta(days=1)
        chart_start_date = last_month_end.replace(day=1)
        chart_end_date = last_month_end + timedelta(days=1)
    elif date_range == 'this_month':
        chart_start_date = today.replace(day=1)
        # Get last day of current month
        if today.month == 12:
            chart_end_date = today.replace(year=today.year + 1, month=1, day=1)
        else:
            chart_end_date = today.replace(month=today.month + 1, day=1)
    elif date_range == 'custom' and start_date_str and end_date_str:
        try:
            chart_start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            # Include the end day fully
            chart_end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() + timedelta(days=1)
        except (ValueError, TypeError):
            pass

    # For legacy templates that still use selected_chart_month
    selected_chart_month = chart_start_date.strftime('%Y-%m')
    
    # Base queryset filtered by user's company
    if request.user.role == 'customer' and request.user.company:
        base_qs = Shipment.objects.filter(
            Q(customer=request.user.company) | 
            Q(created_by=request.user) |
            Q(order__created_by=request.user)
        ).distinct()
        order_qs = Order.objects.filter(
            Q(receiver=request.user.company) | 
            Q(created_by=request.user)
        ).distinct()
        invoice_qs = filter_by_user_company(Invoice.objects.all(), request.user)
    else:
        base_qs = filter_by_user_company(Shipment.objects.all(), request.user)
        order_qs = filter_by_user_company(Order.objects.all(), request.user, company_field='receiver')
        invoice_qs = filter_by_user_company(Invoice.objects.all(), request.user)
    
    # Stat cards
    active_shipments = base_qs.filter(
        status__in=['pending', 'dispatched', 'in_transit', 'approved', 'invoiced']
    ).count()
    
    monthly_revenue = base_qs.filter(
        status__in=['delivered', 'invoiced', 'paid']
    ).filter(
        Q(actual_delivery_date__gte=chart_start_date, actual_delivery_date__lt=chart_end_date) | 
        Q(actual_delivery_date__isnull=True, estimated_delivery_date__gte=chart_start_date, estimated_delivery_date__lt=chart_end_date)
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
        actual_delivery_date__lte=F('estimated_delivery_date')
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
            status__in=['delivered', 'invoiced', 'paid']
        ).filter(
            Q(actual_delivery_date__gte=month_start_date, actual_delivery_date__lte=month_end_date) |
            Q(actual_delivery_date__isnull=True, estimated_delivery_date__gte=month_start_date, estimated_delivery_date__lte=month_end_date)
        ).aggregate(total=Sum('revenue'))['total'] or 0
        
        months.append(month_date.strftime('%b'))
        revenue_data.append(float(month_revenue))
    
    # Shipment status distribution - dynamic for all choices
    status_counts = base_qs.filter(
        created_at__date__gte=chart_start_date,
        created_at__date__lt=chart_end_date,
    ).values('status').annotate(count=Count('id'))
    status_counts_dict = {item['status']: item['count'] for item in status_counts}
    
    status_data = []
    status_labels = []
    for code, label in Shipment.STATUS_CHOICES:
        status_data.append(status_counts_dict.get(code, 0))
        status_labels.append(label)

    # Order status distribution
    order_status_counts = order_qs.filter(
        created_at__date__gte=chart_start_date,
        created_at__date__lt=chart_end_date,
    ).values('status').annotate(count=Count('id'))
    open_count = 0
    complete_count = 0
    for item in order_status_counts:
        if item['status'] in ['delivered', 'closed']:
            complete_count += item['count']
        else:
            open_count += item['count']

    order_status_data = [open_count, complete_count]
    order_status_labels = ['Open', 'Complete']
    
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
        'date_range': date_range,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'chart_month_options': chart_month_options,
        
        # Recent shipments
        'recent_shipments': recent_shipments,
    }
    return render(request, 'dashboard.html', context)


@login_required
def shipment_list(request):
    """List all shipments with filters and AJAX support"""
    from apps.inventory.models import Material
    from django.contrib.auth import get_user_model
    User = get_user_model()

    base_qs = Shipment.objects.select_related('customer', 'shipper', 'consignee', 'order').all()
    if request.user.role == 'customer' and request.user.company:
        shipments = base_qs.filter(
            Q(customer=request.user.company) | 
            Q(created_by=request.user) |
            Q(order__created_by=request.user)
        ).distinct()
    else:
        shipments = filter_by_user_company(base_qs, request.user)
    
    # Search
    search = request.GET.get('search')
    if search:
        shipments = shipments.filter(
            Q(shipment_number__icontains=search) |
            Q(tracking_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(shipper__name__icontains=search) |
            Q(consignee__name__icontains=search) |
            Q(order__order_number__icontains=search)
        ).distinct()
    
    # Scope filter (All, Company, Personal)
    # Only admins can see 'all' or 'company' scope. Others default to 'personal'.
    is_admin = getattr(request.user, 'is_admin', False)
    default_scope = 'all' if is_admin else 'personal'
    scope = request.GET.get('scope', default_scope)
    
    # Enforce restriction
    if not is_admin and scope != 'personal':
        scope = 'personal'

    if scope == 'personal':
        shipments = shipments.filter(created_by=request.user)
    elif scope == 'company' and request.user.company_id:
        shipments = shipments.filter(
            Q(customer_id=request.user.company_id) |
            Q(shipper_id=request.user.company_id) |
            Q(consignee_id=request.user.company_id)
        ).distinct()

    # --- Advanced Multi-select Filters ---
    statuses = request.GET.getlist('status')
    if statuses:
        shipments = shipments.filter(status__in=statuses)
    
    types = request.GET.getlist('type')
    if types:
        shipments = shipments.filter(shipment_type__in=types)
    
    supplier_ids = [v for v in request.GET.getlist('supplier') if v]
    if supplier_ids:
        shipments = shipments.filter(shipper_id__in=supplier_ids)
        
    receiver_ids = [v for v in request.GET.getlist('receiver') if v]
    if receiver_ids:
        shipments = shipments.filter(consignee_id__in=receiver_ids)
        
    carrier_ids = [v for v in request.GET.getlist('carrier') if v]
    if carrier_ids:
        shipments = shipments.filter(carrier_id__in=carrier_ids)
        
    material_names = [v for v in request.GET.getlist('material') if v]
    if material_names:
        shipments = shipments.filter(items__material_name__in=material_names).distinct()
        
    material_types = [v for v in request.GET.getlist('material_type') if v]
    if material_types:
        mat_names = Material.objects.filter(tenant=request.user.tenant, material_type__in=material_types).values_list('name', flat=True)
        shipments = shipments.filter(items__material_name__in=mat_names).distinct()

    # Pickup/Delivery Number logic
    def filter_number(qs, field, mode, val):
        if mode == 'set':
            return qs.filter(**{f"{field}__isnull": False}).exclude(**{field: ''})
        if mode == 'unset':
            return qs.filter(Q(**{f"{field}__isnull": True}) | Q(**{field: ''}))
        if mode == 'contains' and val:
            return qs.filter(**{f"{field}__icontains": val})
        return qs

    shipments = filter_number(shipments, 'pickup_number', request.GET.get('pickup_number_mode'), request.GET.get('pickup_number_val'))
    shipments = filter_number(shipments, 'delivery_number', request.GET.get('delivery_number_mode'), request.GET.get('delivery_number_val'))

    pickup_radius = request.GET.get('pickup_radius', '250')
    dest_radius = request.GET.get('destination_radius', '250')

    # Locations (Text Search)
    pickup_loc_text = request.GET.get('pickup_location_text')
    if pickup_loc_text:
        # For now, we search by text. Radius logic can be added here if geocoding is set up.
        shipments = shipments.filter(
            Q(pickup_location__name__icontains=pickup_loc_text) |
            Q(origin_address__icontains=pickup_loc_text) |
            Q(origin_city__icontains=pickup_loc_text)
        ).distinct()
        
    dest_loc_text = request.GET.get('destination_location_text')
    if dest_loc_text:
        shipments = shipments.filter(
            Q(destination_location__name__icontains=dest_loc_text) |
            Q(destination_address__icontains=dest_loc_text) |
            Q(destination_city__icontains=dest_loc_text)
        ).distinct()

    shipping_term_ids = [v for v in request.GET.getlist('shipping_term') if v]
    if shipping_term_ids:
        shipments = shipments.filter(shipping_terms_id__in=shipping_term_ids)
        
    representative_ids = [v for v in request.GET.getlist('representative') if v]
    if representative_ids:
        shipments = shipments.filter(representative_id__in=representative_ids)
        
    tag_ids = [v for v in request.GET.getlist('tag') if v]
    if tag_ids:
        shipments = shipments.filter(tags__id__in=tag_ids).distinct()

    # Date range filter
    date_from = request.GET.get('date_from')
    if date_from:
        shipments = shipments.filter(pickup_date__gte=date_from)
    date_to = request.GET.get('date_to')
    if date_to:
        shipments = shipments.filter(pickup_date__lte=date_to)
    
    # Sorting
    sort_lookup = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'pickup_newest': '-pickup_date',
        'pickup_oldest': 'pickup_date',
        'delivery_newest': '-estimated_delivery_date',
        'delivery_oldest': 'estimated_delivery_date',
    }
    sort_param = request.GET.get('sort', 'newest')
    sort_by = sort_lookup.get(sort_param, '-created_at')
    shipments = shipments.order_by(sort_by)
    
    # Drawer Context
    user_tenant = request.user.tenant
    all_companies = Company.plain_objects.all().order_by('name')
    
    # AJAX Rendering
    if request.GET.get('ajax') == '1':
        paginator = Paginator(shipments, 25)
        page = request.GET.get('page')
        shipments_page = paginator.get_page(page)
        return render(request, 'shipments/list_partial.html', {'shipments': shipments_page})

    paginator = Paginator(shipments, 25)
    page = request.GET.get('page')
    shipments_page = paginator.get_page(page)
    
    context = {
        'shipments': shipments_page,
        'status_choices': Shipment.STATUS_CHOICES,
        'type_choices': Shipment.SHIPMENT_TYPE_CHOICES,
        'suppliers': all_companies,
        'receivers': all_companies,
        'carriers': all_companies.filter(company_type='carrier'),
        'warehouses': Warehouse.plain_objects.filter(tenant=user_tenant).order_by('name'),
        # Unique materials from ShipmentItem names
        'materials': sorted(list(set(ShipmentItem.objects.all().values_list('material_name', flat=True)))),
        'material_types': Material.objects.filter(tenant=user_tenant).values_list('material_type', flat=True).distinct().order_by('material_type'),
        'shipping_terms': ShippingTerm.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name'),
        'representatives': User.objects.filter(tenant=user_tenant, is_active=True).order_by('first_name'),
        'tags': Tag.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name'),
        'filters': {
            'search': search or '',
            'scope': scope,
            'status_list': statuses,
            'type_list': types,
            'supplier_list': supplier_ids,
            'receiver_list': receiver_ids,
            'carrier_list': carrier_ids,
            'material_list': material_names,
            'material_type_list': material_types,
            'pickup_location_text': pickup_loc_text or '',
            'pickup_radius': pickup_radius,
            'destination_location_text': dest_loc_text or '',
            'destination_radius': dest_radius,
            'shipping_term_list': shipping_term_ids,
            'representative_list': representative_ids,
            'tag_list': tag_ids,
            'pickup_number_mode': request.GET.get('pickup_number_mode', ''),
            'pickup_number_val': request.GET.get('pickup_number_val', ''),
            'delivery_number_mode': request.GET.get('delivery_number_mode', ''),
            'delivery_number_val': request.GET.get('delivery_number_val', ''),
            'date_from': date_from or '',
            'date_to': date_to or '',
            'sort_param': sort_param,
        }
    }
    return render(request, 'shipments/list.html', context)


@login_required
def shipment_detail(request, pk):
    """Shipment detail view with tracking map"""
    # Filter by tenant first to avoid 404s for shipments in other tenants
    shipment_queryset = Shipment.objects.select_related('customer', 'carrier', 'shipper', 'consignee', 'order', 'created_by')
    if request.user.tenant:
        shipment_queryset = shipment_queryset.filter(tenant=request.user.tenant)
    
    shipment = get_object_or_404(shipment_queryset, pk=pk)
    
    # Get all comments for this shipment
    comments = shipment.comments.select_related('user').all().order_by('-created_at')
    if shipment.created_by_id == request.user.id or (
        shipment.order_id and getattr(shipment.order, 'created_by_id', None) == request.user.id
    ):
        pass
    else:
        check_company_access(shipment.customer, request.user)
    
    # Get milestones and history
    from itertools import chain
    milestones = shipment.milestones.all()
    history_events = shipment.history.all()
    
    # Combined history sorted by time
    all_history = sorted(
        chain(milestones, history_events),
        key=lambda x: getattr(x, 'timestamp', getattr(x, 'created_at', None)),
        reverse=True
    )
    
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
    
    commissions = shipment.commissions.select_related('representative').all()
    commission_total = sum((c.amount or 0) for c in commissions) if commissions else 0
    net_profit = shipment.gross_profit - commission_total

    context = {
        'shipment': shipment,
        'milestones': milestones,
        'all_history': all_history,
        'documents': documents,
        'containers': containers,
        'invoices': invoices,
        'users': CustomUser.objects.filter(tenant=request.user.tenant, is_active=True).order_by('first_name'),
        'companies': Company.objects.all().order_by('name'),
        'map_data': json.dumps(map_data),
        'next_invoice_number': Invoice.generate_invoice_number(shipment) if hasattr(Invoice, 'generate_invoice_number') else "Generating...",
        'today': timezone.now().date(),
        'download_invoice_id': request.session.pop('download_invoice_id', None),
        'tracking_update_url': f"/shipments/{shipment.pk}/tracking/update/",
        'warehouses': Warehouse.plain_objects.filter(tenant=request.user.tenant).order_by('name'),
        'suppliers': Company.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)).order_by('name'),
        'customers': Company.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True), company_type='customer').order_by('name'),
        'carriers': Company.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True), company_type='carrier').order_by('name'),
        'tags': Tag.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)).order_by('name'),
        'shipping_terms': ShippingTerm.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)).order_by('name'),
        'packaging_types': PackagingType.objects.all().order_by('name'),
        'shipment_types': Shipment.SHIPMENT_TYPE_CHOICES,
        'comments': comments,
        'commissions': commissions,
        'commission_total': commission_total,
        'net_profit': net_profit,
    }
    return render(request, 'shipments/detail.html', context)


@login_required
@require_POST
def shipment_commission_add(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    if request.user.tenant and shipment.tenant_id != request.user.tenant_id:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)

    commission_type = (request.POST.get('commission_type') or 'fixed').strip()
    representative_id = request.POST.get('representative') or None
    paid_date_raw = (request.POST.get('paid_date') or '').strip()

    percentage_raw = (request.POST.get('percentage') or '').strip()
    amount_raw = (request.POST.get('amount') or '').strip()

    representative = None
    if representative_id:
        representative = CustomUser.objects.filter(tenant=request.user.tenant, pk=representative_id).first()

    percentage = None
    if percentage_raw:
        try:
            percentage = Decimal(str(percentage_raw))
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, 'Invalid percentage.')
            return redirect('shipments:shipment_detail', pk=pk)

    amount = None
    if amount_raw:
        try:
            amount = Decimal(str(amount_raw))
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, 'Invalid amount.')
            return redirect('shipments:shipment_detail', pk=pk)

    paid_date = None
    if paid_date_raw:
        try:
            paid_date = datetime.fromisoformat(paid_date_raw).date()
        except ValueError:
            messages.error(request, 'Invalid paid date.')
            return redirect('shipments:shipment_detail', pk=pk)

    if commission_type == 'fixed':
        if amount is None:
            messages.error(request, 'Amount is required for Fixed commission.')
            return redirect('shipments:shipment_detail', pk=pk)
        final_amount = amount
    else:
        if amount is not None:
            final_amount = amount
        else:
            if percentage is None:
                messages.error(request, 'Percentage is required for this commission type.')
                return redirect('shipments:shipment_detail', pk=pk)

            if commission_type == 'gross_profit_pct':
                base = shipment.gross_profit
            elif commission_type == 'material_cost_pct':
                base = shipment.cost
            elif commission_type == 'material_sale_pct':
                base = shipment.revenue
            else:
                messages.error(request, 'Invalid commission type.')
                return redirect('shipments:shipment_detail', pk=pk)

            final_amount = (Decimal(str(base)) * percentage) / Decimal('100')

    ShipmentCommission.objects.create(
        shipment=shipment,
        representative=representative,
        commission_type=commission_type,
        percentage=percentage,
        amount=final_amount,
        paid_date=paid_date,
    )
    messages.success(request, 'Commission added.')
    return redirect('shipments:shipment_detail', pk=pk)


@login_required
@require_POST
def add_comment(request, pk):
    """AJAX view to add a new comment to a shipment"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    # Check access (similar to shipment_detail)
    if request.user.tenant and shipment.tenant_id != request.user.tenant_id:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    text = request.POST.get('text', '').strip()
    if not text:
        return JsonResponse({'error': 'Comment text cannot be empty'}, status=400)
        
    comment = ShipmentComment.objects.create(
        shipment=shipment,
        user=request.user,
        text=text
    )
    
    # Return formatted data for frontend
    return JsonResponse({
        'ok': True,
        'comment': {
            'id': comment.id,
            'user': comment.user.get_full_name() or comment.user.username,
            'text': comment.text,
            'created_at': comment.created_at.strftime('%b %d, %Y %H:%M'),
            'is_author': True
        }
    })



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
            
        # Create OrderEvent if linked to an order
        if shipment.order_id:
            from apps.orders.models import OrderEvent
            OrderEvent.objects.create(
                order=shipment.order,
                event_type='status_updated',
                description=f"Shipment {shipment.shipment_number} status updated to {shipment.get_status_display()}.",
                created_by=request.user
            )

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

    def _first_item_payload(post_data):
        return {
            'weight': post_data.get('items_ui[0][weight]', 0) or 0,
            'number_of_pieces': post_data.get('items_ui[0][pieces]', 1) or 1,
        }

    order_qs = Order.objects.select_related('supplier', 'receiver').all().order_by('-created_at')
    if request.user.role == 'customer' and request.user.company:
        order_qs = order_qs.filter(Q(receiver=request.user.company) | Q(created_by=request.user))
    else:
        order_qs = filter_by_user_company(order_qs, request.user, company_field='receiver')

    order_id = request.GET.get('order_id') or request.POST.get('order_id')
    if not order_id:
        messages.error(request, 'Please select an order before creating a shipment.')
        return redirect('orders:order_list')

    order = get_object_or_404(order_qs, pk=order_id)
    user_tenant = request.user.tenant

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                if request.user.role == 'customer' and request.user.company:
                    customer_id = request.user.company_id
                else:
                    customer_id = request.POST.get('customer') or order.receiver_id
                carrier_id = request.POST.get('carrier')
                shipper_id = request.POST.get('shipper') or order.supplier_id
                consignee_id = request.POST.get('consignee') or order.receiver_id
                
                # Handle locations
                pickup_loc_id = request.POST.get('pickup_location_ui') or (str(order.source_location_id) if order and order.source_location_id else None)
                dest_loc_id = request.POST.get('destination_location_ui') or (str(order.destination_location_id) if order and order.destination_location_id else None)

                # Create shipment
                shipment = Shipment(
                    order=order,
                    customer_id=customer_id,
                    carrier_id=carrier_id or None,
                    shipper_id=shipper_id or None,
                    consignee_id=consignee_id or None,
                    shipment_type=request.POST.get('shipment_type', 'road'),
                    tracking_number=request.POST.get('tracking_number', ''),
                    status='pending',
                    
                    # Origin
                    pickup_location_id=pickup_loc_id if pickup_loc_id and not pickup_loc_id.startswith('temp_') else None,
                    origin_address=request.POST.get('origin_address', ''),
                    origin_city=request.POST.get('origin_city', ''),
                    origin_state=request.POST.get('origin_state', ''),
                    origin_country=request.POST.get('origin_country', 'USA'),
                    origin_postal_code=request.POST.get('origin_postal_code', ''),
                    pickup_contact=request.POST.get('pickup_contact_ui', ''),
                    pickup_email=request.POST.get('pickup_email_ui', ''),
                    pickup_contact_phone=request.POST.get('pickup_contact_phone_ui', ''),
                    pickup_number=request.POST.get('pickup_number_ui', ''),
                    pickup_appointment_type=request.POST.get('pickup_appointment_ui', 'fcfs'),
                    
                    # Destination
                    destination_location_id=dest_loc_id if dest_loc_id and not dest_loc_id.startswith('temp_') else None,
                    destination_address=request.POST.get('destination_address', ''),
                    destination_city=request.POST.get('destination_city', ''),
                    destination_state=request.POST.get('destination_state', ''),
                    destination_country=request.POST.get('destination_country', 'USA'),
                    destination_postal_code=request.POST.get('destination_postal_code', ''),
                    delivery_contact=request.POST.get('delivery_contact_ui', ''),
                    delivery_email=request.POST.get('delivery_email_ui', ''),
                    delivery_contact_phone=request.POST.get('delivery_contact_phone_ui', ''),
                    delivery_number=request.POST.get('delivery_number_ui', ''),
                    delivery_appointment_type=request.POST.get('delivery_appointment_ui', 'fcfs'),
                    
                    # Schedule
                    pickup_date=request.POST.get('pickup_date') or None,
                    estimated_delivery_date=request.POST.get('estimated_delivery_date') or None,
                    
                    # Cargo
                    total_weight=request.POST.get('total_weight', 0) or 0,
                    total_volume=request.POST.get('total_volume', 0) or 0,
                    number_of_pieces=request.POST.get('number_of_pieces', 0) or 0,
                    commodity_description=request.POST.get('commodity_description', ''),

                    # Commercial
                    shipping_terms_id=request.POST.get('shipping_terms_ui') or None,
                    representative_id=request.POST.get('representative_ui') or None,

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
                )
                shipment.created_by = request.user
                shipment.tenant = request.user.tenant
                shipment._current_user = request.user
                shipment.save()

                # Save tags
                tag_ids = request.POST.getlist('tags_ui')
                shipment.tags.set(tag_ids)

                # Save items
                items_data = _parse_items_from_post(request.POST)
                calculated_weight = 0
                calculated_pieces = 0
                
                for item_data in items_data:
                    inv_item = None
                    if item_data['material_id'] and str(item_data['material_id']).isdigit():
                        inv_item = InventoryItem.objects.filter(pk=item_data['material_id']).first()
                        
                        # Deduct stock if item is from inventory
                        if inv_item:
                            try:
                                qty_to_deduct = float(item_data.get('weight') or 0)
                                if qty_to_deduct > 0:
                                    inv_item.quantity = max(0, inv_item.quantity - int(qty_to_deduct))
                                    inv_item.save()
                                    logger.info(f"Deducted {qty_to_deduct} from {inv_item.product_name} during Shipment {shipment.shipment_number}. New stock: {inv_item.quantity}")
                            except Exception as e:
                                logger.warning(f"Stock deduction failed for item {item_data['material_id']} in Shipment {shipment.shipment_number}: {e}")
                    
                    try:
                        calculated_weight += float(item_data.get('weight') or 0)
                    except (ValueError, TypeError):
                        pass
                        
                    try:
                        calculated_pieces += int(item_data.get('pieces') or 0)
                    except (ValueError, TypeError):
                        pass
                    
                    ShipmentItem.objects.create(
                        shipment=shipment,
                        inventory_item=inv_item,
                        material_name=inv_item.product_name if inv_item else item_data['material_id'] or "Unknown Material",
                        weight=item_data['weight'],
                        weight_unit=item_data['weight_unit'],
                        gross_weight=item_data['gross_weight'],
                        gross_weight_unit=item_data['gross_weight_unit'],
                        tare_weight=item_data['tare_weight'],
                        tare_weight_unit=item_data['tare_weight_unit'],
                        packaging=item_data['packaging'],
                        is_palletized=item_data['is_palletized'],
                        pieces=item_data['pieces'],
                        buy_price=item_data['buy_price'],
                        sell_price=item_data['sell_price'],
                        price_unit=item_data['price_unit'],
                    )
                
                # Update shipment totals if they were missing from the form
                update_shipment = False
                try:
                    form_weight = float(request.POST.get('total_weight') or 0)
                except (ValueError, TypeError):
                    form_weight = 0
                    
                if form_weight <= 0 and calculated_weight > 0:
                    shipment.total_weight = calculated_weight
                    update_shipment = True
                
                try:
                    form_pieces = int(request.POST.get('number_of_pieces') or 0)
                except (ValueError, TypeError):
                    form_pieces = 0
                    
                if form_pieces <= 1 and calculated_pieces > 1:
                    shipment.number_of_pieces = calculated_pieces
                    update_shipment = True
                    
                if update_shipment:
                    shipment.save(update_fields=['total_weight', 'number_of_pieces', 'updated_at'])
                
                # Copy commercial details to order if not set
                if order:
                    order.shipping_terms_id = request.POST.get('shipping_terms_ui') or None
                    order.representative_id = request.POST.get('representative_ui') or None
                    order.save()
                    
                    # Update tags
                    order_tag_ids = request.POST.getlist('tags_ui')
                    if order_tag_ids:
                        order.tags.set(order_tag_ids)
                
                # Create initial milestone
                ShipmentMilestone.objects.create(
                    shipment=shipment,
                    status='Shipment Created',
                    location=shipment.origin_city,
                    notes=f'Shipment created in system. Driver: {shipment.driver_name or "Not assigned"} | Vehicle: {shipment.vehicle_number or "Not assigned"}',
                    created_by=request.user
                )

                logger.info(f'Shipment created: {shipment.shipment_number} for {shipment.customer} by {request.user}')
                
                # Create Lifecycle Event for the Order
                if order:
                    from apps.orders.models import OrderEvent
                    OrderEvent.objects.create(
                        order=order,
                        event_type='shipment_created',
                        description=f"Shipment {shipment.shipment_number} was created and linked to this order.",
                        created_by=request.user
                    )
                messages.success(request, f'Shipment {shipment.shipment_number} created successfully!')
                next_url = request.GET.get('next') or request.POST.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('shipments:shipment_detail', pk=shipment.pk)
        except Exception as e:
            logger.error(f"Error creating shipment for order {order.order_number}: {e}")
            messages.error(request, f"Error creating shipment: {e}")
            # Fall through to re-render form with errors
    
    # Match Order create dropdown sources exactly so the supplier list is identical.
    all_companies = Company.plain_objects.all().order_by('name')
    suppliers = all_companies
    customers = all_companies.filter(company_type='customer')
    carriers = all_companies.filter(company_type='carrier')
    warehouses = Warehouse.plain_objects.filter(tenant=user_tenant).order_by('name')
    inventory_items = InventoryItem.plain_objects.all()
    tags = Tag.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
    shipping_terms = ShippingTerm.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
    representatives = CustomUser.objects.filter(tenant=user_tenant, is_active=True).order_by('first_name', 'username')
    packaging_types = PackagingType.objects.all().order_by('name')
    
    is_first_shipment = not order.shipments.exists()
    
    # --- Context for Contact Pre-filling ---
    # Fetch unique contacts from existing shipments of this order
    shipments = order.shipments.all().order_by('-created_at')
    
    pickup_contacts = []
    seen_pickup = set()
    for s in shipments:
        if s.pickup_contact and s.pickup_contact not in seen_pickup:
            pickup_contacts.append({
                'name': s.pickup_contact,
                'email': s.pickup_email,
                'phone': s.pickup_contact_phone
            })
            seen_pickup.add(s.pickup_contact)

    delivery_contacts = []
    seen_delivery = set()
    for s in shipments:
        if s.delivery_contact and s.delivery_contact not in seen_delivery:
            delivery_contacts.append({
                'name': s.delivery_contact,
                'email': s.delivery_email,
                'phone': s.delivery_contact_phone
            })
            seen_delivery.add(s.delivery_contact)
    
    context = {
        'order': order,
        'orders': order_qs,
        'selected_order_id': str(order.pk),
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
        'default_pieces': int(order.total_pieces) if order.total_pieces else 0,
        'default_weight': order.total_manifest_weight if order.total_manifest_weight else 0,
        'is_create': True,
        'is_first_shipment': is_first_shipment,
        'initial_items': order.manifest_items.all() if is_first_shipment else [],
        'previous_pickup_contacts': pickup_contacts,
        'previous_delivery_contacts': delivery_contacts,
    }
    return render(request, 'shipments/form.html', context)


@login_required
def shipment_edit(request, pk):
    """Edit existing shipment"""
    shipment = get_object_or_404(Shipment, pk=pk)

    def _first_item_payload(post_data):
        return {
            'weight': post_data.get('items_ui[0][weight]', 0) or 0,
            'number_of_pieces': post_data.get('items_ui[0][pieces]', 0) or 0,
        }
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Update shipment
                shipment._current_user = request.user
                shipment.customer_id = request.POST.get('customer') or shipment.customer_id
                shipment.carrier_id = request.POST.get('carrier') or shipment.carrier_id
                shipment.shipper_id = request.POST.get('shipper') or shipment.shipper_id
                shipment.consignee_id = request.POST.get('consignee') or shipment.consignee_id
                shipment.shipment_type = request.POST.get('shipment_type', 'road')
                shipment.tracking_number = request.POST.get('tracking_number', '')

                # Handle locations
                pickup_loc_id = request.POST.get('pickup_location_ui')
                if pickup_loc_id:
                    if pickup_loc_id.startswith('temp_addr_'):
                        shipment.pickup_location_id = None
                        shipment.origin_address = pickup_loc_id.replace('temp_addr_', '')
                    else:
                        shipment.pickup_location_id = pickup_loc_id
                else:
                    shipment.pickup_location_id = None
                    
                dest_loc_id = request.POST.get('destination_location_ui')
                if dest_loc_id:
                    if dest_loc_id.startswith('temp_addr_'):
                        shipment.destination_location_id = None
                        shipment.destination_address = dest_loc_id.replace('temp_addr_', '')
                    else:
                        shipment.destination_location_id = dest_loc_id
                else:
                    shipment.destination_location_id = None
                
                # Origin
                shipment.origin_address = request.POST.get('origin_address', '')
                shipment.origin_city = request.POST.get('origin_city', '')
                shipment.origin_state = request.POST.get('origin_state', '')
                shipment.origin_country = request.POST.get('origin_country', 'USA')
                shipment.origin_postal_code = request.POST.get('origin_postal_code', '')
                shipment.pickup_contact = request.POST.get('pickup_contact_ui', '')
                shipment.pickup_email = request.POST.get('pickup_email_ui', '')
                shipment.pickup_contact_phone = request.POST.get('pickup_contact_phone_ui', '')
                shipment.pickup_number = request.POST.get('pickup_number_ui', '')
                shipment.pickup_appointment_type = request.POST.get('pickup_appointment_ui', '')
                
                # Destination
                shipment.destination_address = request.POST.get('destination_address', '')
                shipment.destination_city = request.POST.get('destination_city', '')
                shipment.destination_state = request.POST.get('destination_state', '')
                shipment.destination_country = request.POST.get('destination_country', 'USA')
                shipment.destination_postal_code = request.POST.get('destination_postal_code', '')
                shipment.delivery_contact = request.POST.get('delivery_contact_ui', '')
                shipment.delivery_email = request.POST.get('delivery_email_ui', '')
                shipment.delivery_contact_phone = request.POST.get('delivery_contact_phone_ui', '')
                shipment.delivery_number = request.POST.get('delivery_number_ui', '')
                shipment.delivery_appointment_type = request.POST.get('delivery_appointment_ui', '')
                
                # Schedule
                shipment.pickup_date = request.POST.get('pickup_date') or None
                shipment.estimated_delivery_date = request.POST.get('estimated_delivery_date') or None
                
                # Cargo
                shipment.total_weight = request.POST.get('total_weight', 0) or 0
                shipment.total_volume = request.POST.get('total_volume', 0) or 0
                shipment.number_of_pieces = request.POST.get('number_of_pieces', 0) or 0
                shipment.commodity_description = request.POST.get('commodity_description', '')

                # Tracking
                shipment.vehicle_number = request.POST.get('vehicle_number', '')
                shipment.driver_name = request.POST.get('driver_name', '')
                shipment.driver_phone = request.POST.get('driver_phone', '')
                
                # Special requirements
                shipment.is_hazmat = request.POST.get('is_hazmat') == 'on'
                shipment.is_temperature_controlled = request.POST.get('is_temperature_controlled') == 'on'
                shipment.requires_insurance = request.POST.get('requires_insurance') == 'on'
                
                # Commercial
                shipment.shipping_terms_id = request.POST.get('shipping_terms_ui') or None
                shipment.representative_id = request.POST.get('representative_ui') or None
                
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

                # Update tags
                tag_ids = request.POST.getlist('tags_ui')
                shipment.tags.set(tag_ids)
                # Sync items if provided in POST
                if 'items_ui[0][weight]' in request.POST:
                    shipment.items.all().delete()
                    items_data = _parse_items_from_post(request.POST)
                    for item_data in items_data:
                        inv_item = None
                        if item_data['material_id'] and str(item_data['material_id']).isdigit():
                            inv_item = InventoryItem.objects.filter(pk=item_data['material_id']).first()
                        
                        ShipmentItem.objects.create(
                            shipment=shipment,
                            inventory_item=inv_item,
                            material_name=inv_item.product_name if inv_item else item_data['material_id'] or "Unknown Material",
                            weight=item_data['weight'],
                            weight_unit=item_data['weight_unit'],
                            gross_weight=item_data['gross_weight'],
                            gross_weight_unit=item_data['gross_weight_unit'],
                            tare_weight=item_data['tare_weight'],
                            tare_weight_unit=item_data['tare_weight_unit'],
                            packaging=item_data['packaging'],
                            is_palletized=item_data['is_palletized'],
                            pieces=item_data['pieces'],
                        buy_price=item_data['buy_price'],
                        sell_price=item_data['sell_price'],
                        price_unit=item_data['price_unit'],
                    )

                # Update associated order commercial details
                if shipment.order:
                    shipment.order.shipping_terms_id = request.POST.get('shipping_terms_ui') or None
                    shipment.order.representative_id = request.POST.get('representative_ui') or None
                    shipment.order.save()
                    
                    # Update order tags
                    if tag_ids:
                        shipment.order.tags.set(tag_ids)
                
                logger.info(f'Shipment updated: {shipment.shipment_number} by {request.user}')
                messages.success(request, f'Shipment {shipment.shipment_number} updated successfully!')
                return redirect('shipments:shipment_detail', pk=shipment.pk)
        except Exception as e:
            logger.error(f"Error updating shipment {shipment.shipment_number}: {e}")
            messages.error(request, f"Error saving shipment: {e}")
            # Fall through to re-render form with errors
    
    # Get data for dropdowns
    user_tenant = request.user.tenant
    all_companies = Company.plain_objects.all().order_by('name')
    suppliers = all_companies
    customers = all_companies.filter(company_type='customer')
    carriers = all_companies.filter(company_type='carrier')
    warehouses = Warehouse.plain_objects.filter(tenant=user_tenant).order_by('name')
    inventory_items = InventoryItem.plain_objects.all()
    tags = Tag.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
    shipping_terms = ShippingTerm.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
    representatives = CustomUser.objects.filter(tenant=user_tenant, is_active=True).order_by('first_name', 'username')
    packaging_types = PackagingType.objects.all().order_by('name')
    
    context = {
        'shipment': shipment,
        'customers': customers,
        'carriers': carriers,
        'suppliers': suppliers,
        'all_companies': all_companies,
        'warehouses': warehouses,
        'inventory_items': inventory_items,
        'tags': tags,
        'shipping_terms': shipping_terms,
        'representatives': representatives,
        'packaging_types': packaging_types,
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
    bol_type = request.POST.get('bol_type', 'receiver')
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
    if is_blind and bol_type == 'receiver':
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
    if is_blind and bol_type == 'shipper':
        consignee_box.append(Paragraph("CONFIDENTIAL", bold_style))
        consignee_box.append(Paragraph("Consignee information withheld", normal_style))
    else:
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





