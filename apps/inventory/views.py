"""
Inventory Views
"""
from decimal import Decimal
import re
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, F, Q, ExpressionWrapper, DecimalField, Case, When, IntegerField
from django.db import transaction
from .models import Warehouse, InventoryItem, Material, InventoryTransaction
from .forms import WarehouseForm, InventoryItemForm, MaterialForm
from apps.accounts.utils import filter_by_user_company, check_company_access
from apps.orders.models import ManifestItem, Order, Tag, ShippingTerm, PackagingType
from apps.accounts.models import CustomUser
from .countries import COUNTRIES
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
            
            # Assign company: check POST data first, then fallback to user's company
            company_id = request.POST.get('company_id')
            if company_id:
                from apps.accounts.models import Company
                warehouse.company = get_object_or_404(Company, id=company_id)
            elif request.user.company:
                warehouse.company = request.user.company
            
            # Check for existing warehouse with same name AND company/tenant
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
                    'company_id': existing.company_id,
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
                'company_id': warehouse.company_id,
                'full_label': str(warehouse)
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors.get_json_data()
            })
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def ajax_locations_for_company(request):
    """AJAX: Return only the main address for a given company_id"""
    company_id = request.GET.get('company_id')
    locations = []
    if company_id:
        from apps.accounts.models import Company
        try:
            company = Company.objects.get(pk=company_id, tenant=request.user.tenant)
            if company.full_address:
                locations.append({
                    'value': f'temp_addr_{company.full_address}',
                    'label': company.full_address,
                    'is_address': True,
                })
        except Company.DoesNotExist:
            pass
    return JsonResponse({'locations': locations})
    
    
@login_required
def ajax_materials_for_company(request):
    """AJAX: Return materials filtered by company_id OR global materials"""
    company_id = request.GET.get('company_id')
    materials = Material.objects.all()
    
    if company_id:
        materials = materials.filter(company_id=company_id)
    else:
        # If no company provided, return nothing to prevent accidental global visibility
        materials = materials.none()
        
    data = [{'value': m.name, 'label': m.name} for m in materials.order_by('name')]
    return JsonResponse({'materials': data})


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

    # Material filter (single select)
    material = request.GET.get('material')
    if material:
        items = items.filter(product_name=material)

    # Have Details: Status
    status = request.GET.get('status')
    if status == 'out_of_stock':
        items = items.filter(quantity=0)
    elif status == 'low_stock':
        items = items.filter(quantity__gt=0, quantity__lte=F('reorder_level'))
    elif status == 'in_stock':
        items = items.filter(quantity__gt=F('reorder_level'))

    # Have Details: Representative
    representative = request.GET.get('representative')
    if representative:
        items = items.filter(representative_id=representative)

    # Have Details: PO/SO number rules
    po_mode = request.GET.get('po_mode')
    po_contains = (request.GET.get('po_contains') or '').strip()
    if po_mode == 'set':
        items = items.exclude(po_number__isnull=True).exclude(po_number__exact='')
    elif po_mode == 'not_set':
        items = items.filter(Q(po_number__isnull=True) | Q(po_number__exact=''))
    elif po_mode == 'contains' and po_contains:
        items = items.filter(po_number__icontains=po_contains)

    # Have Details: Price range + unit
    price_unit = request.GET.get('price_unit')
    price_min = request.GET.get('price_min')
    price_max = request.GET.get('price_max')
    include_no_price = request.GET.get('include_no_price')
    if price_unit:
        items = items.filter(price_unit=price_unit)
    if price_min not in (None, ''):
        try:
            items = items.filter(unit_cost__gte=Decimal(str(price_min)))
        except Exception:
            pass
    if price_max not in (None, ''):
        try:
            items = items.filter(unit_cost__lte=Decimal(str(price_max)))
        except Exception:
            pass
    if not include_no_price and (price_min not in (None, '') or price_max not in (None, '')):
        # Treat 0.00 as "no listed price"
        items = items.exclude(unit_cost=0)

    # Have Details: Weight range + unit (offered_weight)
    weight_unit = request.GET.get('weight_unit')
    weight_min = request.GET.get('weight_min')
    weight_max = request.GET.get('weight_max')
    if weight_unit:
        items = items.filter(offered_weight_unit=weight_unit)
    if weight_min not in (None, ''):
        try:
            items = items.filter(offered_weight__gte=Decimal(str(weight_min)))
        except Exception:
            pass
    if weight_max not in (None, ''):
        try:
            items = items.filter(offered_weight__lte=Decimal(str(weight_max)))
        except Exception:
            pass

    # Have Details: Packaging
    packaging = request.GET.get('packaging')
    if packaging:
        items = items.filter(packaging=packaging)

    # Have Details: Shipping Terms
    shipping_term = request.GET.get('shipping_term')
    if shipping_term:
        items = items.filter(shipping_terms_id=shipping_term)

    # Have Details: Lot number rules
    lot_mode = request.GET.get('lot_mode')
    lot_contains = (request.GET.get('lot_contains') or '').strip()
    if lot_mode == 'set':
        items = items.exclude(lot_number__isnull=True).exclude(lot_number__exact='')
    elif lot_mode == 'not_set':
        items = items.filter(Q(lot_number__isnull=True) | Q(lot_number__exact=''))
    elif lot_mode == 'contains' and lot_contains:
        items = items.filter(lot_number__icontains=lot_contains)

    # Have Details: Tag
    tag = request.GET.get('tag')
    if tag:
        items = items.filter(tags__id=tag).distinct()

    # Have Details: Archived (interpreted as inactive warehouse)
    archived = request.GET.get('archived')
    if archived == '1':
        items = items.filter(warehouse__is_active=False)
    elif archived == '0' or archived is None:
        # Default show non-archived (active warehouses)
        items = items.filter(warehouse__is_active=True)

    # Typical Properties (Material-derived)
    typ_grade = request.GET.get('typ_grade')
    typ_form = request.GET.get('typ_form')
    typ_color = request.GET.get('typ_color')
    typ_product_type = request.GET.get('typ_product_type')
    if any([typ_grade, typ_form, typ_color, typ_product_type]):
        mats = Material.objects.filter(tenant=request.user.tenant)
        if typ_grade:
            mats = mats.filter(grade=typ_grade)
        if typ_form:
            mats = mats.filter(product_type=typ_form)
        if typ_color:
            mats = mats.filter(color=typ_color)
        if typ_product_type:
            mats = mats.filter(material_type=typ_product_type)
        items = items.filter(product_name__in=mats.values_list('name', flat=True))

    # Physical Properties (UI only for now): keep any `ph_` values after refresh
    physical_ctx = {k: (v or '').strip() for k, v in request.GET.items() if k.startswith('ph_')}
    mechanical_ctx = {k: (v or '').strip() for k, v in request.GET.items() if k.startswith('me_')}
    
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
        total_weight=Sum('offered_weight'),
        total_value=Sum('val'),
        total_count=Count('id')
    )

    sort_by = sort_lookup.get(sort_param, '-created_at')
    items = items.order_by(sort_by)
    
    paginator = Paginator(items, 25)
    page = request.GET.get('page')
    items_page = paginator.get_page(page)

    # Packaging options for filter dropdown should match the full packaging type list
    # (same set used in manifest items), not just whatever happens to exist in inventory rows.
    packaging_options = list(PackagingType.objects.order_by('name').values_list('name', flat=True))

    # Also include any extra packaging values that exist on inventory rows but aren't in PackagingType yet.
    inventory_packaging_values = list(
        InventoryItem.objects
        .exclude(packaging__isnull=True)
        .exclude(packaging__exact='')
        .values_list('packaging', flat=True)
    )
    seen = {p.lower() for p in packaging_options if isinstance(p, str)}
    for v in inventory_packaging_values:
        if not isinstance(v, str):
            continue
        v = v.strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        packaging_options.append(v)
     
    context = {
        'items': items_page,
        'warehouses': Warehouse.objects.filter(is_active=True),
        'warehouse_filter': warehouse_id,
        'search': search,
        'low_stock_filter': low_stock,
        'material_filter': material,
        'scope': scope,
        'sort_param': sort_param,
        'stats': stats,
        'materials': sorted(list(set(InventoryItem.objects.all().values_list('product_name', flat=True)))),
        # Have Details options
        'representatives': CustomUser.objects.filter(tenant=request.user.tenant, is_active=True).order_by('username'),
        'shipping_terms': ShippingTerm.objects.filter(tenant=request.user.tenant).order_by('name'),
        'tags': Tag.objects.filter(tenant=request.user.tenant).order_by('name'),
        'packaging_options': packaging_options,
        'price_units': ['per lbs', 'per kgs', 'per MT', 'per ST'],
        'weight_units': ['lbs', 'kgs', 'MT', 'ST'],
        # Have Details current values
        'have_status': status,
        'have_representative': representative or '',
        'have_po_mode': po_mode or '',
        'have_po_contains': po_contains,
        'have_price_unit': price_unit or '',
        'have_price_min': price_min or '',
        'have_price_max': price_max or '',
        'have_include_no_price': bool(include_no_price),
        'have_weight_unit': weight_unit or '',
        'have_weight_min': weight_min or '',
        'have_weight_max': weight_max or '',
        'have_packaging': packaging or '',
        'have_shipping_term': shipping_term or '',
        'have_lot_mode': lot_mode or '',
        'have_lot_contains': lot_contains,
        'have_tag': tag or '',
        'have_archived': archived or '0',
        # Typical current values
        'typ_grade': typ_grade or '',
        'typ_form': typ_form or '',
        'typ_color': typ_color or '',
        'typ_product_type': typ_product_type or '',
        # Typical dropdown options
        'typical_grade_options': sorted(set(Material.objects.filter(tenant=request.user.tenant).exclude(grade='').values_list('grade', flat=True))),
        'typical_form_options': sorted(set(Material.objects.filter(tenant=request.user.tenant).exclude(product_type='').values_list('product_type', flat=True))),
        'typical_color_options': sorted(set(Material.objects.filter(tenant=request.user.tenant).exclude(color='').values_list('color', flat=True))),
        'typical_product_type_options': sorted(set(Material.objects.filter(tenant=request.user.tenant).exclude(material_type='').values_list('material_type', flat=True))),
        # Optical current values (UI only for now)
        'opt_b_value_min': request.GET.get('opt_b_value_min') or '',
        'opt_b_value_max': request.GET.get('opt_b_value_max') or '',
        'opt_haze_min': request.GET.get('opt_haze_min') or '',
        'opt_haze_max': request.GET.get('opt_haze_max') or '',
        'opt_gloss_min': request.GET.get('opt_gloss_min') or '',
        'opt_gloss_max': request.GET.get('opt_gloss_max') or '',
        'opt_l_value_min': request.GET.get('opt_l_value_min') or '',
        'opt_l_value_max': request.GET.get('opt_l_value_max') or '',
        'opt_whiteness_min': request.GET.get('opt_whiteness_min') or '',
        'opt_whiteness_max': request.GET.get('opt_whiteness_max') or '',
        'opt_transmittance_min': request.GET.get('opt_transmittance_min') or '',
        'opt_transmittance_max': request.GET.get('opt_transmittance_max') or '',
        'opt_a_value_min': request.GET.get('opt_a_value_min') or '',
        'opt_a_value_max': request.GET.get('opt_a_value_max') or '',
        'opt_tio2_min': request.GET.get('opt_tio2_min') or '',
        'opt_tio2_max': request.GET.get('opt_tio2_max') or '',
        'opt_light_fastness_min': request.GET.get('opt_light_fastness_min') or '',
        'opt_light_fastness_max': request.GET.get('opt_light_fastness_max') or '',
        'opt_weather_fastness_min': request.GET.get('opt_weather_fastness_min') or '',
        'opt_weather_fastness_max': request.GET.get('opt_weather_fastness_max') or '',
        # Thermal current values
        'th_melting_min': request.GET.get('th_melting_min') or '',
        'th_melting_max': request.GET.get('th_melting_max') or '',
        'th_hdt_min': request.GET.get('th_hdt_min') or '',
        'th_hdt_max': request.GET.get('th_hdt_max') or '',
        'th_vicat_min': request.GET.get('th_vicat_min') or '',
        'th_vicat_max': request.GET.get('th_vicat_max') or '',
        'th_tg_min': request.GET.get('th_tg_min') or '',
        'th_tg_max': request.GET.get('th_tg_max') or '',
        'th_clte_min': request.GET.get('th_clte_min') or '',
        'th_clte_max': request.GET.get('th_clte_max') or '',
        'th_conductivity_min': request.GET.get('th_conductivity_min') or '',
        'th_conductivity_max': request.GET.get('th_conductivity_max') or '',
        'th_gelation_min': request.GET.get('th_gelation_min') or '',
        'th_gelation_max': request.GET.get('th_gelation_max') or '',
        'th_max_proc_min': request.GET.get('th_max_proc_min') or '',
        'th_max_proc_max': request.GET.get('th_max_proc_max') or '',
        # Electrical current values
        'el_dielectric_const_min': request.GET.get('el_dielectric_const_min') or '',
        'el_dielectric_const_max': request.GET.get('el_dielectric_const_max') or '',
        'el_dielectric_strength_min': request.GET.get('el_dielectric_strength_min') or '',
        'el_dielectric_strength_max': request.GET.get('el_dielectric_strength_max') or '',
        'el_dissipation_min': request.GET.get('el_dissipation_min') or '',
        'el_dissipation_max': request.GET.get('el_dissipation_max') or '',
        'el_surface_res_min': request.GET.get('el_surface_res_min') or '',
        'el_surface_res_max': request.GET.get('el_surface_res_max') or '',
        'el_insulation_res_min': request.GET.get('el_insulation_res_min') or '',
        'el_insulation_res_max': request.GET.get('el_insulation_res_max') or '',
        'el_conductivity_min': request.GET.get('el_conductivity_min') or '',
        'el_conductivity_max': request.GET.get('el_conductivity_max') or '',
        'el_arc_res_min': request.GET.get('el_arc_res_min') or '',
        'el_arc_res_max': request.GET.get('el_arc_res_max') or '',
        # Regulatory current values
        'reg_country_origin_list': [v.strip() for v in request.GET.getlist('reg_country_origin') if v.strip()],
        'reg_recycled_cert': (request.GET.get('reg_recycled_cert') or '').strip(),
        'reg_fda': (request.GET.get('reg_fda') or '').strip(),
        # Other current values
        'oth_ul94': (request.GET.get('oth_ul94') or '').strip(),
        'oth_dry_temp_min': request.GET.get('oth_dry_temp_min') or '',
        'oth_dry_temp_max': request.GET.get('oth_dry_temp_max') or '',
        'oth_dry_time_min': request.GET.get('oth_dry_time_min') or '',
        'oth_dry_time_max': request.GET.get('oth_dry_time_max') or '',
        'oth_proc_temp_min': request.GET.get('oth_proc_temp_min') or '',
        'oth_proc_temp_max': request.GET.get('oth_proc_temp_max') or '',
        'oth_tack_free_min': request.GET.get('oth_tack_free_min') or '',
        'oth_tack_free_max': request.GET.get('oth_tack_free_max') or '',
        'oth_colorant': (request.GET.get('oth_colorant') or '').strip(),
        'oth_additive': (request.GET.get('oth_additive') or '').strip(),
        # Dropdown options (static for now; we can refine later)
        'recycled_cert_options': ['ISCC PLUS', 'SCS Recycled Content', 'GRS', 'RCS', 'UL 2809', 'Other'],
        'ul94_options': ['HB', 'V-2', 'V-1', 'V-0', '5VB', '5VA'],
        'colorant_type_options': ['None', 'Carbon Black', 'TiO2', 'Color Masterbatch', 'Dye', 'Other'],
        'additive_type_options': ['None', 'UV Stabilizer', 'Antioxidant', 'Flame Retardant', 'Impact Modifier', 'Slip/Anti-block', 'Other'],
        'country_options': COUNTRIES,
        'durometer_scale_options': ['Shore A', 'Shore D', 'Shore OO', 'Rockwell R', 'Rockwell M', 'Rockwell E', 'Other'],
    }
    context.update(physical_ctx)
    context.update(mechanical_ctx)
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
            
            # Associate with company if provided
            company_id = request.POST.get('company') # From the MaterialForm which we should update
            if not company_id:
                # Try getting it from the InventoryItemForm company field (if passed via JS)
                company_id = request.POST.get('company_id_context')
                
            if company_id:
                from apps.accounts.models import Company
                material.company = get_object_or_404(Company, id=company_id)
            elif request.user.company:
                material.company = request.user.company
            
            from django.db import IntegrityError
            try:
                material.save()
                
                # Log History if company is associated
                if material.company:
                    from apps.accounts.models import CompanyHistory
                    CompanyHistory.objects.create(
                        company=material.company,
                        user=request.user,
                        action="Added a new Company Material",
                        description=f"Created and associated new material {material.name}.",
                        icon="fas fa-plus-circle"
                    )
                
                return JsonResponse({
                    'status': 'success',
                    'id': material.id,
                    'name': material.name,
                    'type': material.material_type or "-",
                    'grade': material.grade or "-",
                    'form': material.product_type or "-",
                    'description': material.description or ""
                })
            except IntegrityError as e:
                # Capture specific conflict message if possible
                error_msg = str(e)
                if 'unique constraint' in error_msg.lower() or 'already exists' in error_msg.lower():
                    friendly_msg = 'A material with this name already exists for this company.'
                else:
                    friendly_msg = f'Database conflict: {error_msg}'
                
                return JsonResponse({
                    'status': 'error',
                    'errors': {'name': [{'message': friendly_msg, 'code': 'unique'}]}
                }, status=400)
        else:
            return JsonResponse({
                'status': 'error',
                'errors': form.errors.get_json_data()
            }, status=400)
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
        palletized_choices = request.POST.getlist('is_palletized')
        offered_weights = request.POST.getlist('offered_weight')
        offered_weight_units = request.POST.getlist('offered_weight_unit')

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
                'offered_weight': offered_weights[i] if i < len(offered_weights) else (quantities[i] if i < len(quantities) else 0),
                'offered_weight_unit': offered_weight_units[i] if i < len(offered_weight_units) else (uoms[i] if i < len(uoms) else 'lbs'),
                'quantity': quantities[i] if (i < len(quantities) and quantities[i]) else (offered_weights[i] if i < len(offered_weights) else 0),
                'unit_of_measure': uoms[i] if (i < len(uoms) and uoms[i]) else (offered_weight_units[i] if i < len(offered_weight_units) else 'lbs'),
                'unit_cost': unit_costs[i] if i < len(unit_costs) else 0,
                'price_unit': price_units[i] if i < len(price_units) else 'per lbs',
                'packaging': packagings[i] if i < len(packagings) else '',
                'pieces': pieces_list[i] if i < len(pieces_list) else 0,
                'is_palletized': is_palletized,
                'description': notes_list[i] if i < len(notes_list) else '',
                # Shared fields
                'po_number': request.POST.get('po_number'),
                'lot_number': request.POST.get('lot_number'),
                'shipping_terms': request.POST.get('shipping_terms'),
                'tags': request.POST.getlist('tags'),
                'company': request.POST.get('company'),
                'representative': request.POST.get('representative'),
            }

            
            form = InventoryItemForm(item_data, user=request.user)
            if form.is_valid():
                with transaction.atomic():
                    item = form.save(commit=False)
                    item.tenant = request.user.tenant
                    if not item.representative:
                        item.representative = request.user
                    
                    item.save()
                    form.save_m2m() # Important for tags

                    # Log Initial Transaction
                    InventoryTransaction.objects.create(
                        item=item,
                        transaction_type='INITIAL',
                        quantity_change=item.quantity,
                        new_quantity=item.quantity,
                        user=request.user,
                        notes="Bulk entry initial stock"
                    )
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
        
        # Default quantity/unit to offered weight if missing
        if not post_data.get('quantity'):
            post_data['quantity'] = post_data.get('offered_weight', 0)
        if not post_data.get('unit_of_measure'):
            post_data['unit_of_measure'] = post_data.get('offered_weight_unit', 'lbs')

        form = InventoryItemForm(post_data, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                item = form.save(commit=False)
                item.tenant = request.user.tenant
                if not item.representative:
                    item.representative = request.user
                
                # Sync offered_weight with quantity on creation
                if not item.pk: # New item
                    item.offered_weight = item.quantity
                    item.offered_weight_unit = item.unit_of_measure
                    
                item.save()
                form.save_m2m()

                # Log Initial Transaction
                InventoryTransaction.objects.create(
                    item=item,
                    transaction_type='INITIAL',
                    quantity_change=item.quantity,
                    new_quantity=item.quantity,
                    user=request.user,
                    notes="Initial stock entry"
                )

            messages.success(request, f"Item '{item.product_name}' successfully added to {warehouse.name}.")
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        initial = {'representative': request.user, 'company': user_company, 'warehouse': warehouse}
        form = InventoryItemForm(initial=initial, user=request.user)

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

        # Default quantity/unit to offered weight if missing
        if not post_data.get('quantity'):
            post_data['quantity'] = post_data.get('offered_weight', 0)
        if not post_data.get('unit_of_measure'):
            post_data['unit_of_measure'] = post_data.get('offered_weight_unit', 'lbs')

        form = InventoryItemForm(post_data, instance=item, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                # If no history exists yet (for old items), create an initial entry first
                if not item.transactions.exists():
                    InventoryTransaction.objects.create(
                        item=item,
                        transaction_type='INITIAL',
                        quantity_change=item.quantity,
                        new_quantity=item.quantity,
                        user=item.representative,
                        notes="Inventory logging started (Existing stock)"
                    )
                
                old_quantity = item.quantity
                item = form.save()
                new_quantity = item.quantity
                
                # Log adjustment if quantity changed
                if old_quantity != new_quantity:
                    change = new_quantity - old_quantity
                    InventoryTransaction.objects.create(
                        item=item,
                        transaction_type='ADJUST',
                        quantity_change=change,
                        new_quantity=new_quantity,
                        user=request.user,
                        notes="Manual stock adjustment"
                    )

            messages.success(request, f"Item '{item.product_name}' updated successfully.")
            return redirect('inventory:item_detail', pk=item.pk)
    else:
        form = InventoryItemForm(instance=item, user=request.user)
    
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

    # 4. Consolidated Partner Companies (Dealers/Stockists/Historical)
    partner_map = {} # cid -> data
    
    def get_or_create_partner(company):
        if not company: return None
        if company.id not in partner_map:
            partner_map[company.id] = {
                'id': company.id,
                'name': company.name,
                'roles': set(),
                'stock_qty': 0,
                'unit': 'lbs',
                'latest_date': None,
                'is_stockist': False
            }
        return partner_map[company.id]

    # From Inventory
    for item in inventory_items:
        p = get_or_create_partner(item.company)
        if p:
            p['roles'].add('Stockist')
            p['is_stockist'] = True
            p['stock_qty'] += float(item.quantity or 0)
            p['unit'] = item.unit_of_measure or 'lbs'
            # Note: We don't have a 'date' on inventory items usually, 
            # maybe use creation date but not crucial for stockists.

    # From Orders
    for order in related_orders:
        s = get_or_create_partner(order.supplier)
        if s:
            s['roles'].add('Supplier')
            if not s['latest_date'] or order.created_at > s['latest_date']:
                s['latest_date'] = order.created_at
        
        r = get_or_create_partner(order.receiver)
        if r:
            r['roles'].add('Receiver')
            if not r['latest_date'] or order.created_at > r['latest_date']:
                r['latest_date'] = order.created_at

    # Sort partners: Stockists first, then by latest date
    sorted_partners = sorted(
        partner_map.values(), 
        key=lambda x: (1 if x['is_stockist'] else 0, x['latest_date'].timestamp() if x['latest_date'] else 0),
        reverse=True
    )

    # Convert roles sets to sorted lists for template use
    for p in sorted_partners:
        p['roles'] = sorted(list(p['roles']))

    context = {
        'material': material,
        'active_tab': request.GET.get('tab', 'details'),
        'inventory_items': inventory_items,
        'total_stock': total_stock,
        'related_orders': list(related_orders)[:10],  # Ensure it's a list for slicing if needed
        'partner_companies': sorted_partners,
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


