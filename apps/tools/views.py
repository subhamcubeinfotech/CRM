"""
Tools Views - Rate comparison and profit calculator
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from decimal import Decimal
import json
import random
from datetime import datetime, timedelta

from .models import RateQuote
import logging

logger = logging.getLogger('apps.shipments')



# Sample carrier data for demo
CARRIERS = [
    {
        'name': 'C.H. Robinson',
        'logo': 'ch_robinson',
        'base_rate_multiplier': 1.0,
        'fuel_surcharge_rate': 0.18,
        'transit_days_min': 3,
        'transit_days_max': 5,
    },
    {
        'name': 'UPS Freight',
        'logo': 'ups',
        'base_rate_multiplier': 1.12,
        'fuel_surcharge_rate': 0.20,
        'transit_days_min': 2,
        'transit_days_max': 4,
    },
    {
        'name': 'XPO Logistics',
        'logo': 'xpo',
        'base_rate_multiplier': 1.08,
        'fuel_surcharge_rate': 0.19,
        'transit_days_min': 3,
        'transit_days_max': 6,
    },
    {
        'name': 'FedEx Freight',
        'logo': 'fedex',
        'base_rate_multiplier': 1.15,
        'fuel_surcharge_rate': 0.21,
        'transit_days_min': 2,
        'transit_days_max': 4,
    },
    {
        'name': 'Old Dominion',
        'logo': 'old_dominion',
        'base_rate_multiplier': 1.05,
        'fuel_surcharge_rate': 0.17,
        'transit_days_min': 3,
        'transit_days_max': 5,
    },
]

# City coordinates for distance calculation
CITY_COORDS = {
    'new york': (40.7128, -74.0060),
    'los angeles': (34.0522, -118.2437),
    'chicago': (41.8781, -87.6298),
    'houston': (29.7604, -95.3698),
    'phoenix': (33.4484, -112.0740),
    'philadelphia': (39.9526, -75.1652),
    'san antonio': (29.4241, -98.4936),
    'san diego': (32.7157, -117.1611),
    'dallas': (32.7767, -96.7970),
    'san jose': (37.3382, -121.8863),
    'miami': (25.7617, -80.1918),
    'seattle': (47.6062, -122.3321),
    'boston': (42.3601, -71.0589),
    'denver': (39.7392, -104.9903),
    'atlanta': (33.7490, -84.3880),
}


def calculate_distance(origin, destination):
    """Calculate approximate distance between two cities"""
    origin_lower = origin.lower()
    dest_lower = destination.lower()
    
    # Extract city name
    origin_city = None
    dest_city = None
    
    for city in CITY_COORDS:
        if city in origin_lower:
            origin_city = city
        if city in dest_lower:
            dest_city = city
    
    if origin_city and dest_city:
        import math
        lat1, lon1 = CITY_COORDS[origin_city]
        lat2, lon2 = CITY_COORDS[dest_city]
        
        # Haversine formula
        R = 3959  # Earth's radius in miles
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        return round(distance)
    
    # Default distance if cities not found
    return random.randint(500, 2500)


def calculate_mock_rates(origin, destination, weight, shipment_type, service_level):
    """Generate mock freight rates"""
    distance = calculate_distance(origin, destination)
    weight = float(weight) if weight else 1000
    
    # Base rate per mile per 100 lbs
    base_rate_per_mile = 0.15
    
    # Service level multiplier
    service_multipliers = {
        'economy': 0.85,
        'standard': 1.0,
        'expedited': 1.35,
    }
    service_mult = service_multipliers.get(service_level, 1.0)
    
    # Shipment type multiplier
    type_multipliers = {
        'ltl': 1.0,
        'partial': 1.15,
        'ftl': 2.5,
    }
    type_mult = type_multipliers.get(shipment_type, 1.0)
    
    rates = []
    for carrier in CARRIERS:
        # Calculate base rate
        base_rate = distance * base_rate_per_mile * (weight / 100) * type_mult * service_mult
        base_rate *= carrier['base_rate_multiplier']
        base_rate = round(base_rate, 2)
        
        # Calculate fuel surcharge
        fuel_surcharge = round(base_rate * carrier['fuel_surcharge_rate'], 2)
        
        # Additional fees
        additional_fees = round(random.uniform(25, 75), 2)
        
        # Insurance
        insurance = round(weight * 0.005, 2)
        
        # Total
        total = round(base_rate + fuel_surcharge + additional_fees + insurance, 2)
        
        rates.append({
            'carrier_name': carrier['name'],
            'carrier_logo': carrier['logo'],
            'base_rate': base_rate,
            'fuel_surcharge': fuel_surcharge,
            'additional_fees': additional_fees,
            'insurance': insurance,
            'total_cost': total,
            'transit_days_min': carrier['transit_days_min'],
            'transit_days_max': carrier['transit_days_max'],
        })
    
    # Sort by total cost
    rates.sort(key=lambda x: x['total_cost'])
    
    # Mark best rate
    if rates:
        rates[0]['is_best_rate'] = True
    
    return rates


@login_required
def rate_comparison(request):
    """Rate comparison and profit calculator page"""
    context = {
        'shipment_types': RateQuote.SHIPMENT_TYPE_CHOICES,
        'service_levels': RateQuote.SERVICE_LEVEL_CHOICES,
    }
    return render(request, 'tools/rate_comparison.html', context)


@login_required
def calculate_rates(request):
    """AJAX endpoint to calculate rates"""
    if request.method == 'POST':
        data = json.loads(request.body)
        
        origin = data.get('origin', '')
        destination = data.get('destination', '')
        weight = data.get('weight', 1000)
        shipment_type = data.get('shipment_type', 'ltl')
        service_level = data.get('service_level', 'standard')
        
        rates = calculate_mock_rates(origin, destination, weight, shipment_type, service_level)
        logger.info(f'Rate comparison calculated: {origin} → {destination}, {weight}lbs, {shipment_type} by {request.user}')
        return JsonResponse({
            'success': True,
            'rates': rates,
            'origin': origin,
            'destination': destination,
            'weight': weight,
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def generate_quote_pdf(request):
    """Generate customer quote PDF"""
    if request.method == 'POST':
        data = json.loads(request.body)
        
        carrier_cost = Decimal(data.get('carrier_cost', 0))
        additional_costs = Decimal(data.get('additional_costs', 0))
        markup_percent = Decimal(data.get('markup_percent', 35))
        customer_quote = Decimal(data.get('customer_quote', 0))
        profit = Decimal(data.get('profit', 0))
        
        # For now, return success
        logger.info(f'Quote PDF generated for {origin} → {destination}, cost ${carrier_cost} by {request.user}')
        return JsonResponse({
            'success': True,
            'message': 'Quote generated successfully',
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})
