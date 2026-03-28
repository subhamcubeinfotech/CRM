"""
Inventory Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, F, Q, ExpressionWrapper, DecimalField, Case, When, IntegerField
from .models import Warehouse, InventoryItem, Material
from .forms import WarehouseForm, InventoryItemForm
from apps.accounts.utils import filter_by_user_company, check_company_access
from apps.orders.models import ManifestItem, Order
import logging
import json
from django.utils import timezone
from datetime import timedelta
from collections import defaultdict

logger = logging.getLogger('apps.inventory')



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
def inventory_item_add_general(request):
    """General view to add inventory item with warehouse selection"""
    
    def resolve_location(val, user):
        """Resolves temp_addr_ strings to Warehouse objects (matching Order behavior)"""
        if not val: return None
        if str(val).startswith('temp_addr_'):
            company = user.company
            if not company: return None
            
            raw_address = str(val).replace('temp_addr_', '')[:200]
            import random
            unique_code = f"LOC-{company.id}-{random.randint(1000, 9999)}"[:20]
            
            hq, created = Warehouse.objects.get_or_create(
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
            return hq
        try:
            return Warehouse.objects.get(pk=val)
        except (Warehouse.DoesNotExist, ValueError):
            return None

    if request.method == 'POST':
        # Manually extract and resolve warehouse since it might be a temp_addr_ string
        warehouse_val = request.POST.get('warehouse')
        resolved_warehouse = resolve_location(warehouse_val, request.user)
        
        # Create a mutable copy of POST data to swap the warehouse value
        post_data = request.POST.copy()
        if resolved_warehouse:
            post_data['warehouse'] = resolved_warehouse.id
        
        form = InventoryItemForm(post_data)
        if form.is_valid():
            item = form.save(commit=False)
            item.tenant = request.user.tenant
            # Set default company if not provided
            if not item.company and request.user.company:
                item.company = request.user.company
            # Set default representative if not provided
            if not item.representative:
                item.representative = request.user
            item.save()
            # Save many-to-many relationships
            form.save_m2m()
            messages.success(request, f"Item '{item.product_name}' successfully added to inventory.")
            return redirect('inventory:item_list')
    else:
        # Filter warehouses and other related objects
        warehouses = Warehouse.objects.filter(is_active=True, is_storage=True)
        if request.user.company:
            warehouses = warehouses.filter(company=request.user.company)
        
        initial = {
            'representative': request.user,
            'company': request.user.company,
        }
        
        if warehouses.count() == 1:
            initial['warehouse'] = warehouses.first()
            
        form = InventoryItemForm(initial=initial)
        form.fields['warehouse'].queryset = warehouses
        
        # Filter representatives, shipping terms, and tags to only show items from the same tenant
        from django.contrib.auth import get_user_model
        from apps.orders.models import ShippingTerm, Tag
        User = get_user_model()
        
        tenant = request.user.tenant
        form.fields['representative'].queryset = User.objects.filter(tenant=tenant, is_active=True)
        form.fields['shipping_terms'].queryset = ShippingTerm.objects.filter(tenant=tenant)
        form.fields['tags'].queryset = Tag.objects.filter(tenant=tenant)
    
    from apps.accounts.models import Company
    user_company = request.user.company
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()
    
    # Show all warehouses in tenant, prioritize user's company (matching Order page)
    warehouses = Warehouse.plain_objects.filter(tenant=request.user.tenant).annotate(
        priority=Case(
            When(company=user_company, then=0),
            default=1,
            output_field=IntegerField(),
        )
    ).order_by('priority', 'name')
        
    context = {
        'form': form,
        'title': 'New Inventory',
        'company': user_company or assign_company,
        'assign_company': assign_company,
        'warehouses': warehouses,
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_item_add(request, pk):
    """Add inventory item to a specific warehouse"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.method == 'POST':
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.warehouse = warehouse
            item.save()
            messages.success(request, f"Item '{item.product_name}' added to {warehouse.name}.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        # Pre-fill warehouse
        form = InventoryItemForm(initial={'warehouse': warehouse})
    
    from apps.accounts.models import Company
    user_company = request.user.company
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()
    
    # Show all warehouses in tenant
    warehouses = Warehouse.plain_objects.filter(tenant=request.user.tenant).annotate(
        priority=Case(
            When(company=user_company, then=0),
            default=1,
            output_field=IntegerField(),
        )
    ).order_by('priority', 'name')
        
    context = {
        'form': form,
        'warehouse': warehouse,
        'company': warehouse.company or assign_company,
        'assign_company': assign_company,
        'warehouses': warehouses,
        'title': f'Add Item to {warehouse.name}',
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_item_edit(request, pk):
    """Edit an existing inventory item"""
    item = get_object_or_404(InventoryItem, pk=pk)
    warehouse = item.warehouse
    
    if request.method == 'POST':
        # Manually resolve warehouse (matching general add)
        warehouse_val = request.POST.get('warehouse')
        # Here we don't necessarily want to allow creating new warehouses during edit, 
        # but for consistency with the "Your Address" feature, we support it.
        from django.db.models import Q # Ensure Q is available if we use it, but here we just use resolve_location helper if redefined or shared.
        # For simplicity in this edit, I'll repeat the logic or just handle plain IDs since edit usually has a fixed warehouse.
        # But the user asked for "EXACTLY like order page", so I'll redefine the helper or make it global in the file.
        
        # Swapping to resolved ID
        post_data = request.POST.copy()
        if warehouse_val and str(warehouse_val).startswith('temp_addr_'):
            # Redefining helper simply for this scope (could be moved to top level later)
            company = request.user.company
            if company:
                raw_address = str(warehouse_val).replace('temp_addr_', '')[:200]
                import random
                unique_code = f"LOC-{company.id}-{random.randint(1000, 9999)}"[:20]
                hq, _ = Warehouse.objects.get_or_create(
                    company=company, tenant=company.tenant, name=raw_address,
                    defaults={'code': unique_code, 'address': company.address_line1, 'city': company.city[:100],
                              'state': company.state[:100], 'country': company.country[:100], 'postal_code': company.postal_code[:20],
                              'phone': company.phone[:20], 'is_storage': False}
                )
                post_data['warehouse'] = hq.id

        form = InventoryItemForm(post_data, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"Item '{item.product_name}' updated successfully.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        form = InventoryItemForm(instance=item)
    
    from apps.accounts.models import Company
    user_company = request.user.company
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()
    
    # Show all warehouses in tenant
    warehouses = Warehouse.plain_objects.filter(tenant=request.user.tenant).annotate(
        priority=Case(
            When(company=user_company, then=0),
            default=1,
            output_field=IntegerField(),
        )
    ).order_by('priority', 'name')
        
    context = {
        'form': form,
        'warehouse': warehouse,
        'company': warehouse.company or assign_company,
        'assign_company': assign_company,
        'warehouses': warehouses,
        'item': item,
        'title': f'Edit {item.product_name}',
    }
    return render(request, 'inventory/item_form.html', context)


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

    # 3. Chart Data (Last 6 months)
    six_months_ago = timezone.now() - timedelta(days=180)
    history = ManifestItem.objects.filter(
        material__icontains=material.name,
        order__created_at__gte=six_months_ago
    ).values('order__created_at', 'buy_price', 'sell_price', 'weight')

    # Aggregate by month using a simple dict to avoid type inference issues
    monthly_buy = defaultdict(list)
    monthly_sell = defaultdict(list)
    monthly_weight = defaultdict(float)
    
    for h in history:
        month_key = h['order__created_at'].strftime('%Y-%m')
        monthly_buy[month_key].append(float(h['buy_price']))
        monthly_sell[month_key].append(float(h['sell_price']))
        monthly_weight[month_key] += float(h['weight'])

    # Prepare chart labels and values (sorted by month)
    sorted_months = sorted(monthly_buy.keys())
    chart_labels = []
    chart_buy_avg = []
    chart_sell_avg = []
    chart_weight = []
    
    for m in sorted_months:
        chart_labels.append(timezone.datetime.strptime(m, '%Y-%m').strftime('%b'))
        chart_buy_avg.append(sum(monthly_buy[m]) / len(monthly_buy[m]) if monthly_buy[m] else 0)
        chart_sell_avg.append(sum(monthly_sell[m]) / len(monthly_sell[m]) if monthly_sell[m] else 0)
        chart_weight.append(monthly_weight[m])

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
        'chart_data': json.dumps({
            'labels': chart_labels,
            'buy': chart_buy_avg,
            'sell': chart_sell_avg,
            'weight': chart_weight
        })
    }
    return render(request, 'inventory/material_detail.html', context)


