"""
Inventory Views
"""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum, F, Q, ExpressionWrapper, DecimalField
from .models import Warehouse, InventoryItem
import logging

logger = logging.getLogger('apps.inventory')



@login_required
def inventory_dashboard(request):
    """Inventory dashboard"""
    total_warehouses = Warehouse.objects.filter(is_active=True).count()
    total_items = InventoryItem.objects.count()
    total_value = InventoryItem.objects.annotate(
        val=ExpressionWrapper(F('quantity') * F('unit_cost'), output_field=DecimalField())
    ).aggregate(total=Sum('val'))['total'] or 0
    low_stock_count = InventoryItem.objects.filter(quantity__lte=F('reorder_level')).count()
    
    context = {
        'total_warehouses': total_warehouses,
        'total_items': total_items,
        'total_value': total_value,
        'low_stock_count': low_stock_count,
        'warehouses': Warehouse.objects.filter(is_active=True)[:5],
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def warehouse_list(request):
    """List all warehouses"""
    warehouses = Warehouse.objects.filter(is_active=True).order_by('name')
    
    paginator = Paginator(warehouses, 25)
    page = request.GET.get('page')
    warehouses = paginator.get_page(page)
    
    context = {
        'warehouses': warehouses,
    }
    return render(request, 'inventory/warehouse_list.html', context)


@login_required
def warehouse_detail(request, pk):
    """Warehouse detail view"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    
    items = warehouse.inventory_items.all()
    total_value = sum(item.total_value for item in items)
    
    context = {
        'warehouse': warehouse,
        'items': items,
        'total_value': total_value,
    }
    return render(request, 'inventory/warehouse_detail.html', context)


@login_required
def inventory_item_list(request):
    """List all inventory items"""
    items = InventoryItem.objects.select_related('warehouse').all()
    
    # Filter by warehouse
    warehouse_id = request.GET.get('warehouse')
    if warehouse_id:
        items = items.filter(warehouse_id=warehouse_id)
    
    # Search
    search = request.GET.get('search')
    if search:
        items = items.filter(
            Q(sku__icontains=search) |
            Q(product_name__icontains=search)
        )
    
    # Low stock filter
    low_stock = request.GET.get('low_stock')
    if low_stock:
        items = [item for item in items if item.is_low_stock]
    
    paginator = Paginator(items, 25)
    page = request.GET.get('page')
    items = paginator.get_page(page)
    
    context = {
        'items': items,
        'warehouses': Warehouse.objects.filter(is_active=True),
        'warehouse_filter': warehouse_id,
        'search': search,
        'low_stock_filter': low_stock,
    }
    return render(request, 'inventory/item_list.html', context)


@login_required
def inventory_item_detail(request, pk):
    """Inventory item detail view"""
    item = get_object_or_404(InventoryItem, pk=pk)
    
    context = {
        'item': item,
    }
    return render(request, 'inventory/item_detail.html', context)


