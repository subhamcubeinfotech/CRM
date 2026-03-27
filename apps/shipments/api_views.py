"""
Shipments API Views
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Shipment
import json


@login_required
def shipment_list_api(request):
    """API endpoint for shipment list"""
    shipments = Shipment.objects.select_related('customer').all()[:50]
    
    data = []
    for s in shipments:
        data.append({
            'id': s.id,
            'shipment_number': s.shipment_number,
            'customer': s.customer.name,
            'origin': s.origin_full,
            'destination': s.destination_full,
            'status': s.get_status_display(),
            'status_code': s.status,
            'shipment_type': s.get_shipment_type_display(),
            'pickup_date': s.pickup_date.isoformat() if s.pickup_date else None,
            'estimated_delivery_date': s.estimated_delivery_date.isoformat() if s.estimated_delivery_date else None,
        })
    
    return JsonResponse({'shipments': data})


@login_required
def shipment_detail_api(request, pk):
    """API endpoint for shipment detail"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    data = {
        'id': shipment.id,
        'shipment_number': shipment.shipment_number,
        'tracking_number': shipment.tracking_number,
        'vehicle_number': shipment.vehicle_number,
        'driver_name': shipment.driver_name,
        'driver_phone': shipment.driver_phone,
        'customer': shipment.customer.name,
        'carrier': shipment.carrier.name if shipment.carrier else None,
        'origin': shipment.origin_full,
        'destination': shipment.destination_full,
        'status': shipment.get_status_display(),
        'status_code': shipment.status,
        'shipment_type': shipment.get_shipment_type_display(),
        'pickup_date': shipment.pickup_date.isoformat() if shipment.pickup_date else None,
        'estimated_delivery_date': shipment.estimated_delivery_date.isoformat() if shipment.estimated_delivery_date else None,
        'actual_delivery_date': shipment.actual_delivery_date.isoformat() if shipment.actual_delivery_date else None,
        'total_weight': float(shipment.total_weight),
        'total_volume': float(shipment.total_volume),
        'number_of_pieces': shipment.number_of_pieces,
        'commodity_description': shipment.commodity_description,
        'is_hazmat': shipment.is_hazmat,
        'is_temperature_controlled': shipment.is_temperature_controlled,
        'requires_insurance': shipment.requires_insurance,
        'quoted_amount': float(shipment.quoted_amount),
        'cost': float(shipment.cost),
        'revenue': float(shipment.revenue),
        'gross_profit': float(shipment.gross_profit),
        'profit_margin': float(shipment.profit_margin),
        'progress_percentage': shipment.progress_percentage,
        'current_location': shipment.current_location_display,
        'last_location_updated_at': shipment.last_location_updated_at.isoformat() if shipment.last_location_updated_at else None,
        'tracking_active': shipment.tracking_active,
    }
    
    return JsonResponse(data)


@login_required
def shipment_calendar_events(request):
    """API endpoint for shipment calendar events formatted for FullCalendar"""
    start = request.GET.get('start')
    end = request.GET.get('end')
    
    from apps.accounts.utils import filter_by_user_company
    from django.db.models import Q
    
    shipments = Shipment.objects.select_related('customer', 'shipper', 'consignee').all()
    if request.user.role == 'customer' and request.user.company:
        shipments = shipments.filter(
            Q(customer=request.user.company) | 
            Q(created_by=request.user) |
            Q(order__created_by=request.user)
        ).distinct()
    else:
        shipments = filter_by_user_company(shipments, request.user)
        
    if start and end:
        s_date = start.split('T')[0]
        e_date = end.split('T')[0]
        shipments = shipments.filter(
            Q(pickup_date__lte=e_date) & 
            (Q(actual_delivery_date__gte=s_date) | Q(estimated_delivery_date__gte=s_date) | Q(estimated_delivery_date__isnull=True))
        )
        
    # Apply additional filters
    status = request.GET.get('status')
    if status:
        shipments = shipments.filter(status=status)
        
    shipment_type = request.GET.get('type')
    if shipment_type:
        shipments = shipments.filter(shipment_type=shipment_type)
        
    search = request.GET.get('search')
    if search:
        shipments = shipments.filter(
            Q(shipment_number__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(origin_city__icontains=search) |
            Q(destination_city__icontains=search)
        )
        
    data = []
    for s in shipments:
        colors = {
            'pending': '#D32F2F',    'dispatched': '#EF6C00',
            'in_transit': '#1976D2', 'delivered': '#2E7D32',
            'approved': '#7B1FA2',   'invoiced': '#00796B',
            'paid': '#558B2F',       'rejected': '#455A64',
        }
        color = colors.get(s.status, '#315efb')
        
        if s.pickup_date:
            data.append({
                'id': f"pu_{s.id}",
                'title': f"PU: {s.shipment_number} - {s.origin_city or '-'}",
                'start': s.pickup_date.isoformat(),
                'url': f"/shipments/{s.id}/",
                'backgroundColor': color,
                'borderColor': color,
            })
            
        delivery_date = s.actual_delivery_date or s.estimated_delivery_date
        if delivery_date:
            data.append({
                'id': f"del_{s.id}",
                'title': f"DEL: {s.shipment_number} - {s.destination_city or '-'}",
                'start': delivery_date.isoformat(),
                'url': f"/shipments/{s.id}/",
                'backgroundColor': color,
                'borderColor': color,
            })
            
    return JsonResponse(data, safe=False)


@login_required
def shipment_tracking_api(request, pk):
    """API endpoint for shipment tracking data"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    # Get combined milestones and history
    combined_history = []
    
    for m in shipment.milestones.all():
        combined_history.append({
            'status': m.status,
            'location': m.location,
            'latitude': float(m.latitude) if m.latitude else None,
            'longitude': float(m.longitude) if m.longitude else None,
            'notes': m.notes,
            'timestamp': m.timestamp.isoformat(),
            'user_name': m.created_by.get_full_name() if m.created_by else 'System',
            'icon': 'fas fa-map-marker-alt'
        })
        
    for h in shipment.history.all():
        combined_history.append({
            'action': h.action,
            'description': h.description,
            'icon': h.icon,
            'timestamp': h.created_at.isoformat(),
            'user_name': h.user.get_full_name() if h.user else 'System'
        })
        
    # Sort combined history by timestamp
    combined_history.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Map data
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
            'label': shipment.current_location_display,
            'updated_at': shipment.last_location_updated_at.isoformat() if shipment.last_location_updated_at else None,
        },
    }

    data = {
        'shipment_number': shipment.shipment_number,
        'status': shipment.status,
        'status_display': shipment.get_status_display(),
        'current_location': shipment.current_location_display,
        'last_location_updated_at': shipment.last_location_updated_at.isoformat() if shipment.last_location_updated_at else None,
        'tracking_active': shipment.tracking_active,
        'vehicle_number': shipment.vehicle_number,
        'driver_name': shipment.driver_name,
        'driver_phone': shipment.driver_phone,
        'milestones': combined_history,
        'map_data': map_data,
    }
    
    return JsonResponse(data)
