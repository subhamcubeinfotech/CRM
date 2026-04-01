"""
Inventory Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, F, Q, ExpressionWrapper, DecimalField, Case, When, IntegerField
from .models import Warehouse, InventoryItem, Material
from .forms import WarehouseForm, InventoryItemForm, MaterialForm
from apps.accounts.utils import filter_by_user_company, check_company_access
from apps.orders.models import ManifestItem, Order
import logging
import json
from django.utils import timezone
from datetime import timedelta
from collections import defaultdict

logger = logging.getLogger('apps.inventory')


def resolve_location(request, warehouse_val):
    """Helper to resolve temp_addr_ strings into Warehouse objects"""
    if not warehouse_val or not str(warehouse_val).startswith('temp_addr_'):
        return warehouse_val
        
    company = request.user.company
    if not company:
        return warehouse_val
        
    raw_address = str(warehouse_val).replace('temp_addr_', '')[:200]
    import random
    unique_code = f"LOC-{company.id}-{random.randint(1000, 9999)}"[:20]
    
    hq, _ = Warehouse.objects.get_or_create(
        company=company,
        tenant=company.tenant,
        name=raw_address,
        defaults={
            'code': unique_code,
            'address': company.address_line1,
            'city': company.city[:100],
            'state': company.state[:100],
            'country': company.country[:100],
            'postal_code': company.postal_code[:20],
            'phone': company.phone[:20],
            'is_storage': False
        }
    )
    return hq.id


@login_required
def ajax_warehouse_create(request):
    """AJAX view to create a warehouse from the side drawer"""
    if request.method == 'POST':
        form = WarehouseForm(request.POST)
        if form.is_valid():
            warehouse = form.save(commit=False)
            
            # Ensure tenant is set
            if hasattr(request.user, 'tenant'):
                warehouse.tenant = request.user.tenant
            
            # Assign company from request (likely current user's company)
            if request.user.company:
                warehouse.company = request.user.company
            
            # Check for existing warehouse with same name AND company/tenant
            # We check name and company to avoid duplicates for the same entity
            existing = Warehouse.objects.filter(
                name=warehouse.name,
                company=warehouse.company,
                tenant=warehouse.tenant
            ).first()
            
            if existing:
                return JsonResponse({
                    'success': True,
                    'is_existing': True,
                    'id': existing.id,
                    'name': existing.name,
                    'full_label': str(existing)
                })

            # Auto-generate a unique code if missing
            if not warehouse.code:
                import random
                warehouse.code = f"W-{random.randint(1000, 9999)}"[:20]
            
            warehouse.save()
            return JsonResponse({
                'success': True,
                'id': warehouse.id,
                'name': warehouse.name,
                'full_label': str(warehouse)
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors.get_json_data()
            })
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def inventory_dashboard(request):
    """Inventory dashboard"""
    total_warehouses = Warehouse.objects.filter(is_active=True, is_storage=True).count()
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
        'warehouses': Warehouse.objects.filter(is_active=True, is_storage=True)[:5],
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def warehouse_list(request):
    """List all warehouses"""
    warehouses = Warehouse.objects.filter(is_active=True, is_storage=True).order_by('name')
    
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
    
    # Fix for items created without tenant (migration/manual entry fix)
    # We use plain_objects to see items regardless of tenant filters
    orphan_items = InventoryItem.plain_objects.filter(warehouse=warehouse, tenant__isnull=True)
    if orphan_items.exists() and warehouse.tenant:
        orphan_items.update(tenant=warehouse.tenant)
    
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
    """List all inventory items with stats and filters"""
    from django.db.models import Sum, Count, F, Q, ExpressionWrapper, DecimalField
    
    items = InventoryItem.objects.select_related('warehouse').all()
    
    # Scope filter
    scope = request.GET.get('scope', 'all')
    if scope == 'personal':
        items = items.filter(warehouse__manager=request.user)
    elif scope == 'company' and request.user.company_id:
        items = items.filter(warehouse__company_id=request.user.company_id)

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
        items = items.filter(quantity__lte=F('reorder_level'))
    
    # Sorting
    sort_param = request.GET.get('sort', 'newest')
    sort_lookup = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'weight_desc': '-quantity',
        'weight_asc': 'quantity',
        'name_asc': 'product_name',
        'name_desc': '-product_name',
        'val_desc': '-val',
    }
    
    # Annotate value for stats and sorting
    items = items.annotate(
        val=ExpressionWrapper(F('quantity') * F('unit_cost'), output_field=DecimalField(max_digits=12, decimal_places=2))
    )
    
    # Stats before pagination
    stats = items.aggregate(
        total_weight=Sum('quantity'),
        total_value=Sum('val'),
        total_count=Count('id')
    )

    sort_by = sort_lookup.get(sort_param, '-created_at')
    items = items.order_by(sort_by)
    
    paginator = Paginator(items, 25)
    page = request.GET.get('page')
    items_page = paginator.get_page(page)
    
    context = {
        'items': items_page,
        'warehouses': Warehouse.objects.filter(is_active=True),
        'warehouse_filter': warehouse_id,
        'search': search,
        'low_stock_filter': low_stock,
        'scope': scope,
        'sort_param': sort_param,
        'stats': stats,
        'materials': sorted(list(set(InventoryItem.objects.all().values_list('product_name', flat=True)))),
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


@login_required
def warehouse_edit(request, pk):
    """Edit warehouse details"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.method == 'POST':
        form = WarehouseForm(request.POST, instance=warehouse)
        if form.is_valid():
            form.save()
            messages.success(request, f"Warehouse '{warehouse.name}' updated successfully.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        form = WarehouseForm(instance=warehouse)
    
    context = {
        'form': form,
        'warehouse': warehouse,
        'title': f'Edit {warehouse.name}',
    }
    return render(request, 'inventory/warehouse_form.html', context)


@login_required
def warehouse_create(request):
    """Create a new warehouse"""
    if request.method == 'POST':
        form = WarehouseForm(request.POST)
        if form.is_valid():
            warehouse = form.save(commit=False)
            warehouse.tenant = request.user.tenant
            warehouse.company = request.user.company
            warehouse.manager = request.user
            warehouse.is_storage = True
            warehouse.save()
            messages.success(request, f"Warehouse '{warehouse.name}' created successfully.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        form = WarehouseForm()
    
    context = {
        'form': form,
        'title': 'Create New Warehouse',
    }
    return render(request, 'inventory/warehouse_form.html', context)


@login_required
def create_material_ajax(request):
    """AJAX view to create a new material"""
    if request.method == 'POST':
        form = MaterialForm(request.POST, request.FILES)
        if form.is_valid():
            material = form.save(commit=False)
            if hasattr(request.user, 'tenant'):
                material.tenant = request.user.tenant
            material.save()
            return JsonResponse({
                'status': 'success',
                'id': material.id,
                'name': material.name
            })
        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def inventory_item_add_general(request):
    """General view to add an inventory item (not starting from a warehouse)"""
    user_company = request.user.company
    from apps.accounts.models import Company
    
    # Aggressively lock to a company if user has none assigned
    if not user_company and request.user.tenant:
        user_company = Company.objects.filter(tenant=request.user.tenant).first()
            
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()

    if request.method == 'POST':
        # Handing Grouped Inventory (Multiple Items)
        product_names = request.POST.getlist('product_name')
        skus = request.POST.getlist('sku')
        
        # Fallback for single item if lists are empty (though frontend should send common names)
        if not product_names and request.POST.get('product_name'):
            product_names = [request.POST.get('product_name')]
            skus = [request.POST.get('sku')]

        # Global fields (shared across all items in this submission)
        warehouse_val = request.POST.get('warehouse')
        resolved_warehouse = resolve_location(request, warehouse_val)
        
        created_count = 0
        
        # Other lists
        quantities = request.POST.getlist('quantity')
        uoms = request.POST.getlist('unit_of_measure')
        unit_costs = request.POST.getlist('unit_cost')
        price_units = request.POST.getlist('price_unit')
        packagings = request.POST.getlist('packaging')
        pieces_list = request.POST.getlist('pieces')
        notes_list = request.POST.getlist('description')
        lot_numbers = request.POST.getlist('lot_number')
        palletized_choices = request.POST.getlist('is_palletized')

        created_count = 0
        error_messages = []

        for i in range(len(product_names)):
            # Convert 'yes'/'no' to boolean for the form/model
            is_palletized = False
            if i < len(palletized_choices):
                is_palletized = (palletized_choices[i] == 'yes')

            item_data = {
                'warehouse': resolved_warehouse,
                'product_name': product_names[i],
                'sku': skus[i] if i < len(skus) else '',
                'quantity': quantities[i] if i < len(quantities) else 0,
                'unit_of_measure': uoms[i] if i < len(uoms) else 'lbs',
                'unit_cost': unit_costs[i] if i < len(unit_costs) else 0,
                'price_unit': price_units[i] if i < len(price_units) else 'per lbs',
                'packaging': packagings[i] if i < len(packagings) else '',
                'pieces': pieces_list[i] if i < len(pieces_list) else 0,
                'is_palletized': is_palletized,
                'description': notes_list[i] if i < len(notes_list) else '',
                # Shared fields
                'po_number': request.POST.get('po_number'),
                'lot_number': lot_numbers[i] if i < len(lot_numbers) else '',
                'shipping_terms': request.POST.get('shipping_terms'),
                'tags': request.POST.getlist('tags'),
            }
            
            form = InventoryItemForm(item_data, user=request.user)
            if form.is_valid():
                item = form.save(commit=False)
                item.tenant = request.user.tenant
                if user_company:
                    item.company = user_company
                if not item.representative:
                    item.representative = request.user
                
                item.save()
                form.save_m2m() # Important for tags
                created_count += 1
            else:
                # Collect errors for each invalid item
                item_label = product_names[i] or f"Item {i+1}"
                for field, errors in form.errors.items():
                    for error in errors:
                        error_messages.append(f"{item_label}: {field.title()} - {error}")

        if created_count > 0:
            messages.success(request, f"Successfully added {created_count} items to inventory.")
            if not error_messages:
                return redirect('inventory:item_list')
        
        if error_messages:
            for msg in error_messages:
                messages.error(request, msg)
    else:
        initial = {
            'representative': request.user,
            'company': user_company,
        }
        form = InventoryItemForm(initial=initial, user=request.user)
        
        # Lock company choices if user has a company (or we locked it to the tenant's only company)
        if user_company:
            form.fields['company'].queryset = Company.objects.filter(id=user_company.id)
            form.fields['company'].disabled = True
        elif request.user.tenant:
            form.fields['company'].queryset = Company.objects.filter(tenant=request.user.tenant)

    # Show all warehouses in tenant, prioritize user's company (matching Order page)
    warehouses = Warehouse.plain_objects.filter(tenant=request.user.tenant).annotate(
        priority=Case(
            When(company=user_company, then=0),
            default=1,
            output_field=IntegerField(),
        )
    ).order_by('priority', 'name')
    
    # Check if "Your Address" already exists as a formal warehouse to avoid duplicates
    hq_exists = False
    if assign_company:
        hq_exists = warehouses.filter(name=assign_company.full_address).exists()
        
    context = {
        'form': form,
        'material_form': MaterialForm(),
        'title': 'New Inventory',
        'company': user_company or assign_company,
        'assign_company': assign_company,
        'warehouses': warehouses,
        'hq_exists': hq_exists,
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_item_add(request, pk):
    """Add inventory item to a specific warehouse"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    user_company = request.user.company
    from apps.accounts.models import Company
    
    # Aggressively lock company
    if not user_company and request.user.tenant:
        user_company = Company.objects.filter(tenant=request.user.tenant).first()
            
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()

    if request.method == 'POST':
        # Manually resolve warehouse
        warehouse_val = request.POST.get('warehouse')
        post_data = request.POST.copy()
        post_data['warehouse'] = resolve_location(request, warehouse_val)
        
        form = InventoryItemForm(post_data, user=request.user)
        if form.is_valid():
            item = form.save(commit=False)
            item.tenant = request.user.tenant
            if user_company:
                item.company = user_company
            if not item.representative:
                item.representative = request.user
            item.save()
            form.save_m2m()
            messages.success(request, f"Item '{item.product_name}' successfully added to {warehouse.name}.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        initial = {'representative': request.user, 'company': user_company, 'warehouse': warehouse}
        form = InventoryItemForm(initial=initial, user=request.user)
        if user_company:
            form.fields['company'].queryset = Company.objects.filter(id=user_company.id)
            form.fields['company'].disabled = True

    # Show all warehouses in tenant, prioritize user's company
    warehouses = Warehouse.plain_objects.filter(tenant=request.user.tenant).annotate(
        priority=Case(When(company=user_company, then=0), default=1, output_field=IntegerField())
    ).order_by('priority', 'name')
    
    hq_exists = False
    if assign_company:
        hq_exists = warehouses.filter(name=assign_company.full_address).exists()
        
    context = {
        'form': form,
        'warehouse': warehouse,
        'company': user_company or assign_company,
        'assign_company': assign_company,
        'warehouses': warehouses,
        'hq_exists': hq_exists,
        'title': f'Add to {warehouse.name}',
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_item_edit(request, pk):
    """Edit an existing inventory item"""
    item = get_object_or_404(InventoryItem, pk=pk)
    warehouse = item.warehouse
    user_company = request.user.company
    from apps.accounts.models import Company
    
    # Aggressively lock to a company if user has none assigned
    if not user_company and request.user.tenant:
        user_company = Company.objects.filter(tenant=request.user.tenant).first()
        
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()
    
    if request.method == 'POST':
        warehouse_val = request.POST.get('warehouse')
        post_data = request.POST.copy()
        post_data['warehouse'] = resolve_location(request, warehouse_val)

        form = InventoryItemForm(post_data, instance=item, user=request.user)
        if form.is_valid():
            item = form.save(commit=False)
            if user_company:
                item.company = user_company
            item.save()
            form.save_m2m()
            messages.success(request, f"Item '{item.product_name}' updated successfully.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        form = InventoryItemForm(instance=item, user=request.user)
        if user_company:
            form.fields['company'].queryset = Company.objects.filter(id=user_company.id)
            form.fields['company'].disabled = True
    
    # Material Form for offcanvas drawer
    material_form = MaterialForm()
    
    # Show all warehouses in tenant
    warehouses = Warehouse.plain_objects.filter(tenant=request.user.tenant).annotate(
        priority=Case(When(company=user_company, then=0), default=1, output_field=IntegerField())
    ).order_by('priority', 'name')
    
    hq_exists = False
    if assign_company:
        hq_exists = warehouses.filter(name=assign_company.full_address).exists()
        
    context = {
        'form': form,
        'material_form': material_form,
        'warehouse': warehouse,
        'company': item.company or assign_company,
        'assign_company': assign_company,
        'warehouses': warehouses,
        'hq_exists': hq_exists,
        'item': item,
        'title': f'Edit {item.product_name}',
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_item_delete(request, pk):
    """Delete an inventory item"""
    item = get_object_or_404(InventoryItem, pk=pk)
    warehouse_pk = item.warehouse.pk
    product_name = item.product_name
    
    if request.method == 'POST':
        item.delete()
        messages.success(request, f"Item '{product_name}' deleted successfully.")
        return redirect('inventory:warehouse_detail', pk=warehouse_pk)
    
    return redirect('inventory:item_detail', pk=pk)


@login_required
def material_detail(request, pk=None):
    """View to display material details, orders, and documents"""
    if pk:
        material = get_object_or_404(Material, pk=pk)
    else:
        name = request.GET.get('name')
        if not name:
            return redirect('inventory:item_list')
        
        # Use get_or_create to handle tenant-aware lookup and creation safely
        material, created = Material.objects.get_or_create(
            name=name,
            tenant=request.user.tenant,
            defaults={
                'material_type': "PE",
                'grade': "Post-Industrial",
                'color': "Mixed",
                'product_type': "Film",
            }
        )
        if created:
            logger.info(f"New material record created via lookup: {name} for tenant {request.user.tenant}")

    # --- Live Data Aggregation ---
    
    # 1. Haves (Inventory)
    inventory_items = InventoryItem.objects.filter(
        Q(product_name__icontains=material.name) | Q(sku__icontains=material.name)
    ).select_related('warehouse')
    total_stock = sum(item.quantity for item in inventory_items)

    # 2. Orders & Pricing History
    manifest_items = ManifestItem.objects.filter(
        material__icontains=material.name
    ).select_related('order').order_by('-order__created_at')
    
    related_orders = []
    seen_orders = set()
    for item in manifest_items:
        if item.order_id not in seen_orders:
            related_orders.append(item.order)
            seen_orders.add(item.order_id)

    # 3. Chart Data
    range_days = request.GET.get('range', '180')
    try:
        days = int(range_days)
    except ValueError:
        days = 180
        
    start_date = timezone.now() - timedelta(days=days)
    end_date = timezone.now()
    
    history = ManifestItem.objects.filter(
        material__icontains=material.name,
        order__created_at__gte=start_date
    ).values('order__created_at', 'buy_price', 'sell_price', 'weight')

    # Determine grouping granularity based on range
    if days <= 30:
        group_format = '%Y-%m-%d'
    elif days <= 90:
        # Weekly grouping could be added here, but for now we'll stick to daily for 30 and monthly for higher
        group_format = '%Y-%m-%d'
    else:
        group_format = '%Y-%m'
        
    # Aggregate data using the determined granularity
    grouped_buy = defaultdict(list)
    grouped_sell = defaultdict(list)
    grouped_weight = defaultdict(float)
    
    for h in history:
        key = h['order__created_at'].strftime(group_format)
        grouped_buy[key].append(float(h['buy_price'] or 0))
        grouped_sell[key].append(float(h['sell_price'] or 0))
        grouped_weight[key] += float(h['weight'] or 0)

    # Prepare chart labels and values (sorted by key)
    sorted_keys = sorted(grouped_buy.keys())
    chart_labels = []
    chart_buy_avg = []
    chart_sell_avg = []
    chart_weight = []
    
    for k in sorted_keys:
        if days <= 90:
            # Display as "Mar 28" for daily/weekly granularity
            label = timezone.datetime.strptime(k, '%Y-%m-%d').strftime('%b %d')
        else:
            # Display as "Mar '26" for monthly granularity
            label = timezone.datetime.strptime(k, '%Y-%m').strftime("%b '%y")
            
        chart_labels.append(label)
        chart_buy_avg.append(sum(grouped_buy[k]) / len(grouped_buy[k]) if grouped_buy[k] else 0)
        chart_sell_avg.append(sum(grouped_sell[k]) / len(grouped_sell[k]) if grouped_sell[k] else 0)
        chart_weight.append(grouped_weight[k])

    # Stats
    avg_buy = sum(chart_buy_avg) / len(chart_buy_avg) if chart_buy_avg else 0
    avg_sell = sum(chart_sell_avg) / len(chart_sell_avg) if chart_sell_avg else 0

    context = {
        'material': material,
        'active_tab': request.GET.get('tab', 'details'),
        'inventory_items': inventory_items,
        'total_stock': total_stock,
        'related_orders': list(related_orders)[:10],  # Ensure it's a list for slicing if needed
        'avg_buy': avg_buy,
        'avg_sell': avg_sell,
        'current_range': str(days),
        'start_date': start_date,
        'end_date': end_date,
        'chart_data': json.dumps({
            'labels': chart_labels,
            'buy': chart_buy_avg,
            'sell': chart_sell_avg,
            'weight': chart_weight
        })
    }
    return render(request, 'inventory/material_detail.html', context)


