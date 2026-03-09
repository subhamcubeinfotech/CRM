from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import logging

logger = logging.getLogger('apps.accounts')


@login_required
def customer_dashboard(request):
    return render(request, 'customers/dashboard.html')

@login_required
def customer_shipments(request):
    return render(request, 'customers/shipments.html')

@login_required
def customer_shipment_detail(request, pk):
    return render(request, 'customers/shipment_detail.html')

@login_required
def customer_invoices(request):
    return render(request, 'customers/invoices.html')

@login_required
def customer_invoice_detail(request, pk):
    return render(request, 'customers/invoice_detail.html')

@login_required
def customer_tracking(request, tracking_number):
    return render(request, 'customers/tracking.html')

@login_required
def request_quote(request):
    return render(request, 'customers/request_quote.html')

@login_required
def customer_inventory(request):
    # Retrieve tenant-scoped inventory available for this customer
    # Show "Have" vs "Need" logic per the requirements
    context = {'inventory_items': []}
    return render(request, 'customers/inventory.html', context)

@login_required
def create_order(request):
    if request.method == 'POST':
        # Logic to create Order based on selected inventory items
        logger.info(f'Customer order creation requested by {request.user}')
        return JsonResponse({'status': 'success', 'order_id': 'ORD-2025-001'})
    return render(request, 'customers/create_order.html')
