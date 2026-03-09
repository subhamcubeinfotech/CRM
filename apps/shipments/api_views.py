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
    }
    
    return JsonResponse(data)


@login_required
def shipment_tracking_api(request, pk):
    """API endpoint for shipment tracking data"""
    shipment = get_object_or_404(Shipment, pk=pk)
    
    # Get milestones
    milestones = []
    for m in shipment.milestones.all():
        milestones.append({
            'status': m.status,
            'location': m.location,
            'latitude': float(m.latitude) if m.latitude else None,
            'longitude': float(m.longitude) if m.longitude else None,
            'notes': m.notes,
            'timestamp': m.timestamp.isoformat(),
        })
    
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
        },
    }
    
    data = {
        'shipment_number': shipment.shipment_number,
        'status': shipment.status,
        'status_display': shipment.get_status_display(),
        'milestones': milestones,
        'map_data': map_data,
    }
    
    return JsonResponse(data)
