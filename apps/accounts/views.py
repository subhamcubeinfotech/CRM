"""
Accounts Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import EmailMessage
from django.conf import settings
from .models import Company, CompanyDocument
from .forms import CompanyForm
from apps.inventory.forms import WarehouseForm
from apps.inventory.models import Material
from apps.orders.models import Tag

from .geocoding import geocode_company
from .utils import filter_by_user_company, check_company_access
from django.db.models import Q
import logging
from collections import defaultdict

logger = logging.getLogger('apps.accounts')


def custom_logout(request):
    """Log out the user and redirect to login page"""
    logout(request)
    return redirect('login')


@login_required
def company_list(request):
    """List companies — filtered by creator unless admin (uses plain_objects)"""
    # Use the tenant-aware manager by default
    companies = Company.objects.prefetch_related('material_tags', 'company_tags').all().order_by('name')

    # If the user is an internal admin, they can see everything via plain_objects
    if request.user.role == 'admin':
        companies = Company.plain_objects.prefetch_related('material_tags', 'company_tags').all().order_by('name')
    
    # For non-admin roles (like customer), further filter by their specific company if needed
    elif request.user.role == 'customer':
        user_company = request.user.company
        if user_company:
            companies = companies.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            companies = companies.filter(created_by=request.user)

    base_companies = companies
    company_type_choices = dict(Company.COMPANY_TYPE_CHOICES)
    crm_status_choices = dict(Company.CRM_STATUS_CHOICES)

    company_type = (request.GET.get('type') or '').strip()
    crm_status = (request.GET.get('status') or '').strip()
    material_id = (request.GET.get('material') or '').strip()
    material_type = (request.GET.get('material_type') or '').strip()
    tag_id = (request.GET.get('tag') or '').strip()
    service = (request.GET.get('service') or '').strip()
    representative_id = (request.GET.get('representative') or '').strip()
    archived = (request.GET.get('archived') or '').strip()
    location = (request.GET.get('location') or '').strip()
    search = (request.GET.get('search') or '').strip()

    if company_type in company_type_choices:
        companies = companies.filter(company_type=company_type)

    if crm_status in crm_status_choices:
        companies = companies.filter(crm_status=crm_status)

    if material_id.isdigit():
        companies = companies.filter(material_tags__pk=int(material_id))

    if material_type:
        companies = companies.filter(material_tags__material_type__icontains=material_type)

    if tag_id.isdigit():
        companies = companies.filter(company_tags__pk=int(tag_id))

    if service:
        companies = companies.filter(services_provided__icontains=service)

    if representative_id.isdigit():
        companies = companies.filter(created_by_id=int(representative_id))

    if archived == 'yes':
        companies = companies.filter(is_active=False)
    elif archived == 'no':
        companies = companies.filter(is_active=True)

    if location:
        companies = companies.filter(
            Q(address_line1__icontains=location) |
            Q(address_line2__icontains=location) |
            Q(city__icontains=location) |
            Q(state__icontains=location) |
            Q(country__icontains=location) |
            Q(postal_code__icontains=location)
        )

    if search:
        companies = companies.filter(
            Q(name__icontains=search) |
            Q(legal_name__icontains=search) |
            Q(city__icontains=search) |
            Q(state__icontains=search) |
            Q(country__icontains=search) |
            Q(services_provided__icontains=search) |
            Q(material_tags__name__icontains=search) |
            Q(company_tags__name__icontains=search)
        )

    companies = companies.distinct()

    available_materials = Material.plain_objects.filter(
        associated_companies__in=base_companies
    ).distinct().order_by('name')
    available_tags = Tag.objects.filter(
        companies__in=base_companies
    ).distinct().order_by('name')
    available_services = sorted({
        service_name.strip()
        for company in base_companies
        for service_name in (company.services_provided or [])
        if str(service_name).strip()
    }, key=str.lower)
    available_locations = sorted({
        value.strip()
        for company in base_companies
        for value in [
            company.full_address,
            ", ".join(filter(None, [company.city, company.state, company.country])),
            ", ".join(filter(None, [company.address_line1, company.city, company.state])),
            ", ".join(filter(None, [company.address_line1, company.address_line2, company.city, company.state, company.country])),
            company.postal_code,
        ]
        if value and str(value).strip()
    }, key=str.lower)
    available_material_types = sorted({
        (material.material_type or material.name).strip()
        for material in available_materials
        if (material.material_type or material.name) and (material.material_type or material.name).strip()
    }, key=str.lower)
    representatives = get_user_model().objects.filter(pk=request.user.pk)

    selected_material = available_materials.filter(pk=int(material_id)).first() if material_id.isdigit() else None
    selected_tag = available_tags.filter(pk=int(tag_id)).first() if tag_id.isdigit() else None
    selected_representative = representatives.filter(pk=int(representative_id)).first() if representative_id.isdigit() else None

    active_filters = []
    if search:
        active_filters.append({'label': 'Search', 'value': search})
    if location:
        active_filters.append({'label': 'Location', 'value': location})
    if company_type in company_type_choices:
        active_filters.append({'label': 'Type', 'value': company_type_choices[company_type]})
    if crm_status in crm_status_choices:
        active_filters.append({'label': 'Status', 'value': crm_status_choices[crm_status]})
    if service:
        active_filters.append({'label': 'Service', 'value': service})
    if selected_material:
        active_filters.append({'label': 'Material', 'value': selected_material.name})
    if material_type:
        active_filters.append({'label': 'Material Type', 'value': material_type})
    if selected_tag:
        active_filters.append({'label': 'Tag', 'value': selected_tag.name})
    if selected_representative:
        active_filters.append({'label': 'Representative', 'value': selected_representative.get_full_name() or selected_representative.username})
    if archived == 'yes':
        active_filters.append({'label': 'Archived', 'value': 'Yes'})
    elif archived == 'no':
        active_filters.append({'label': 'Archived', 'value': 'No'})

    query_params = request.GET.copy()
    query_params.pop('page', None)
    pagination_query = query_params.urlencode()

    paginator = Paginator(companies, 25)
    page = request.GET.get('page')
    companies = paginator.get_page(page)
    for company in companies:
        if company.full_address and (company.latitude is None or company.longitude is None):
            geocode_company(company, save=True)
    context = {
        'companies': companies,
        'company_type': company_type,
        'crm_status': crm_status,
        'material_id': material_id,
        'material_type': material_type,
        'tag_id': tag_id,
        'service': service,
        'representative_id': representative_id,
        'archived': archived,
        'location': location,
        'search': search,
        'available_materials': available_materials,
        'available_tags': available_tags,
        'available_services': available_services,
        'available_locations': available_locations,
        'available_material_types': available_material_types,
        'representatives': representatives,
        'active_filters': active_filters,
        'selected_material': selected_material,
        'selected_tag': selected_tag,
        'selected_representative': selected_representative,
        'company_type_choices': Company.COMPANY_TYPE_CHOICES,
        'crm_status_choices': Company.CRM_STATUS_CHOICES,
        'pagination_query': pagination_query,
    }
    return render(request, 'accounts/company_list.html', context)


def _visible_companies_for_user(user):
    # Use tenant-aware manager by default
    companies = Company.objects.prefetch_related('material_tags').all().order_by('name')

    # Internal admins see everything
    if user.role == 'admin':
        companies = Company.plain_objects.prefetch_related('material_tags').all().order_by('name')
    
    # Customer role further restricted
    elif user.role == 'customer':
        user_company = user.company
        if user_company:
            companies = companies.filter(Q(created_by=user) | Q(pk=user_company.pk))
        else:
            companies = companies.filter(created_by=user)
    return companies


def _company_role_label(company_id, supplier_ids, receiver_ids):
    is_supplier = company_id in supplier_ids
    is_receiver = company_id in receiver_ids
    if is_supplier and is_receiver:
        return 'both'
    if is_supplier:
        return 'supplier'
    if is_receiver:
        return 'receiver'
    return 'partner'


def _company_tier(activity_score):
    if activity_score >= 25:
        return 'tier_1'
    if activity_score >= 10:
        return 'tier_2'
    return 'tier_3'


@login_required
def map_dashboard(request):
    """Full-page geo dashboard with advanced filters and product-type color coding."""
    companies = _visible_companies_for_user(request.user)

    # Keep coordinates warm for records with valid addresses (Limited to 5 at a time to avoid timeout)
    for company in companies[:5]:
        if company.full_address and (company.latitude is None or company.longitude is None):
            geocode_company(company, save=True)

    from apps.ai_assistant.models import BuyerRequirement
    from apps.orders.models import Order
    from apps.shipments.models import Shipment
    from apps.inventory.models import InventoryItem
    from apps.ai_assistant.enhancements import classify_product_type

    company_ids = list(companies.values_list('id', flat=True))

    inventory_items = InventoryItem.objects.filter(
        tenant=request.user.tenant,
        company_id__in=company_ids,
        quantity__gt=0,
    ).select_related('company')

    requirements = BuyerRequirement.objects.filter(
        tenant=request.user.tenant,
        is_fulfilled=False,
        buyer_id__in=company_ids,
    ).select_related('buyer')

    orders = Order.objects.filter(tenant=request.user.tenant).filter(
        Q(supplier_id__in=company_ids) | Q(receiver_id__in=company_ids)
    )
    shipments = Shipment.objects.filter(tenant=request.user.tenant).filter(
        Q(shipper_id__in=company_ids) | Q(consignee_id__in=company_ids) | Q(customer_id__in=company_ids)
    )

    supplier_ids = set(orders.values_list('supplier_id', flat=True)).union(
        set(shipments.values_list('shipper_id', flat=True))
    )
    receiver_ids = set(orders.values_list('receiver_id', flat=True)).union(
        set(shipments.values_list('consignee_id', flat=True)),
        set(shipments.values_list('customer_id', flat=True)),
        set(requirements.values_list('buyer_id', flat=True)),
    )

    product_types = set()
    industries = set()
    cities = set()
    tiers = {'tier_1', 'tier_2', 'tier_3'}

    inv_by_company = defaultdict(list)
    for item in inventory_items:
        inv_by_company[item.company_id].append(item)
        product_types.add(classify_product_type(item.product_name, item.description))

    req_by_company = defaultdict(list)
    for req in requirements:
        req_by_company[req.buyer_id].append(req)
        product_types.add(classify_product_type(req.material_name, req.material_type))

    activity_score = defaultdict(int)
    for sid in supplier_ids:
        if sid:
            activity_score[sid] += 5
    for rid in receiver_ids:
        if rid:
            activity_score[rid] += 5
    for cid, items in inv_by_company.items():
        activity_score[cid] += len(items)
    for cid, reqs in req_by_company.items():
        activity_score[cid] += len(reqs)

    for company in companies:
        industries.add(company.get_company_type_display())
        cities.add(company.city or 'Unknown')

    context = {
        'industry_options': sorted([x for x in industries if x]),
        'city_options': sorted([x for x in cities if x]),
        'tier_options': [('tier_1', 'Tier 1'), ('tier_2', 'Tier 2'), ('tier_3', 'Tier 3')],
        'product_type_options': sorted([x for x in product_types if x]),
        'role_options': [('supplier', 'Supplier'), ('receiver', 'Receiver'), ('both', 'Both')],
    }
    return render(request, 'accounts/map_dashboard.html', context)


@login_required
def map_dashboard_data(request):
    """JSON API powering the full map with server-side filtering."""
    companies = _visible_companies_for_user(request.user)

    from apps.ai_assistant.models import BuyerRequirement
    from apps.orders.models import Order
    from apps.shipments.models import Shipment
    from apps.inventory.models import InventoryItem
    from apps.ai_assistant.enhancements import classify_product_type

    selected_cities = [x.strip().lower() for x in request.GET.getlist('city') if x.strip()]
    selected_industries = [x.strip().lower() for x in request.GET.getlist('industry') if x.strip()]
    selected_tiers = [x.strip().lower() for x in request.GET.getlist('tier') if x.strip()]
    selected_product_types = [x.strip().lower() for x in request.GET.getlist('product_type') if x.strip()]
    selected_roles = [x.strip().lower() for x in request.GET.getlist('role') if x.strip()]
    search = (request.GET.get('search') or '').strip().lower()

    company_ids = list(companies.values_list('id', flat=True))
    inv_qs = InventoryItem.objects.filter(
        tenant=request.user.tenant,
        company_id__in=company_ids,
        quantity__gt=0
    ).select_related('company', 'warehouse')
    req_qs = BuyerRequirement.objects.filter(
        tenant=request.user.tenant,
        is_fulfilled=False,
        buyer_id__in=company_ids
    ).select_related('buyer')

    orders = Order.objects.filter(tenant=request.user.tenant).filter(
        Q(supplier_id__in=company_ids) | Q(receiver_id__in=company_ids)
    )
    shipments = Shipment.objects.filter(tenant=request.user.tenant).filter(
        Q(shipper_id__in=company_ids) | Q(consignee_id__in=company_ids) | Q(customer_id__in=company_ids)
    )

    supplier_ids = set(orders.values_list('supplier_id', flat=True)).union(
        set(shipments.values_list('shipper_id', flat=True))
    )
    receiver_ids = set(orders.values_list('receiver_id', flat=True)).union(
        set(shipments.values_list('consignee_id', flat=True)),
        set(shipments.values_list('customer_id', flat=True)),
        set(req_qs.values_list('buyer_id', flat=True)),
    )

    inv_by_company = defaultdict(list)
    for item in inv_qs:
        inv_by_company[item.company_id].append(item)

    req_by_company = defaultdict(list)
    for req in req_qs:
        req_by_company[req.buyer_id].append(req)

    activity_score = defaultdict(int)
    for cid, items in inv_by_company.items():
        activity_score[cid] += len(items)
    for cid, reqs in req_by_company.items():
        activity_score[cid] += len(reqs)
    for sid in supplier_ids:
        if sid:
            activity_score[sid] += 5
    for rid in receiver_ids:
        if rid:
            activity_score[rid] += 5

    markers = []
    for c in companies:
        if c.latitude is None or c.longitude is None:
            continue

        role = _company_role_label(c.id, supplier_ids, receiver_ids)
        industry = c.get_company_type_display()
        tier = _company_tier(activity_score.get(c.id, 0))

        inv_items = inv_by_company.get(c.id, [])
        req_items = req_by_company.get(c.id, [])

        product_type_set = set()
        for item in inv_items:
            product_type_set.add(classify_product_type(item.product_name, item.description))
        for req in req_items:
            product_type_set.add(classify_product_type(req.material_name, req.material_type))
        if not product_type_set:
            for mt in c.material_tags.all():
                product_type_set.add(classify_product_type(mt.name, mt.material_type, mt.product_type))
        if not product_type_set:
            product_type_set.add('Other')

        product_types = sorted(product_type_set)
        primary_product_type = product_types[0]

        total_inventory_qty = 0
        top_inventory = []
        for item in sorted(inv_items, key=lambda x: x.quantity, reverse=True)[:3]:
            qty_float = float(item.quantity or 0)
            total_inventory_qty += qty_float
            top_inventory.append({
                'name': item.product_name,
                'quantity': qty_float,
                'unit': item.unit_of_measure,
            })
        if len(inv_items) > 3:
            total_inventory_qty += sum(float(i.quantity or 0) for i in inv_items[3:])

        top_requirements = [{
            'material': r.material_name,
            'quantity': float(r.quantity_needed or 0),
            'unit': r.unit,
        } for r in req_items[:3]]

        haystack = ' '.join([
            c.name or '', c.city or '', c.state or '', industry,
            ' '.join(product_types),
            role,
        ]).lower()

        if search and search not in haystack:
            continue
        if selected_cities and (c.city or 'unknown').lower() not in selected_cities:
            continue
        if selected_industries and industry.lower() not in selected_industries:
            continue
        if selected_tiers and tier not in selected_tiers:
            continue
        if selected_roles and role not in selected_roles:
            continue
        if selected_product_types and not any(pt.lower() in selected_product_types for pt in product_types):
            continue

        markers.append({
            'id': c.id,
            'name': c.name,
            'lat': float(c.latitude),
            'lng': float(c.longitude),
            'city': c.city or '',
            'state': c.state or '',
            'industry': industry,
            'tier': tier,
            'role': role,
            'product_types': product_types,
            'primary_product_type': primary_product_type,
            'inventory': {
                'item_count': len(inv_items),
                'total_quantity': round(total_inventory_qty, 2),
                'top_items': top_inventory,
            },
            'requirements': {
                'open_count': len(req_items),
                'top_items': top_requirements,
            },
            'detail_url': f"/companies/{c.id}/",
        })

    return JsonResponse({
        'markers': markers,
        'count': len(markers),
    })


@login_required
def customer_list(request):
    """List customers — filtered by creator unless admin (uses plain_objects)"""
    # Use the tenant-aware manager by default
    customers = Company.objects.filter(company_type='customer').order_by('name')

    # If the user is an internal admin, they can see everything via plain_objects
    if request.user.role == 'admin':
        customers = Company.plain_objects.filter(company_type='customer').order_by('name')
    
    # For customer roles, filter by their specific creator or company
    elif request.user.role == 'customer':
        user_company = request.user.company
        if user_company:
            customers = customers.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            customers = customers.filter(created_by=request.user)
    
    # Search
    search = request.GET.get('search')
    if search:
        customers = customers.filter(name__icontains=search)
    
    paginator = Paginator(customers, 25)
    page = request.GET.get('page')
    customers = paginator.get_page(page)
    
    context = {
        'customers': customers,
        'search': search,
    }
    return render(request, 'accounts/customer_list.html', context)


@login_required
def carrier_list(request):
    """List carriers — filtered by creator unless admin (uses plain_objects)"""
    # Use the tenant-aware manager by default
    carriers = Company.objects.filter(company_type='carrier').order_by('name')

    # If the user is an internal admin, they can see everything via plain_objects
    if request.user.role == 'admin':
        carriers = Company.plain_objects.filter(company_type='carrier').order_by('name')
    
    # For customer roles, filter by their specific creator or company
    elif request.user.role == 'customer':
        user_company = request.user.company
        if user_company:
            carriers = carriers.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            carriers = carriers.filter(created_by=request.user)
    
    # Search
    search = request.GET.get('search')
    if search:
        carriers = carriers.filter(name__icontains=search)
    
    paginator = Paginator(carriers, 25)
    page = request.GET.get('page')
    carriers = paginator.get_page(page)
    
    context = {
        'carriers': carriers,
        'search': search,
    }
    return render(request, 'accounts/carrier_list.html', context)


@login_required
def company_detail(request, pk):
    """View company details"""
    company = get_object_or_404(Company.plain_objects, pk=pk)
    
    from django.db.models import Q
    from apps.orders.models import Order
    from apps.shipments.models import Shipment
    
    orders = Order.objects.filter(
        Q(supplier=company) | Q(receiver=company)
    ).order_by('-created_at')[:20]

    shipments = Shipment.objects.filter(
        Q(customer=company) | Q(carrier=company) | Q(shipper=company) | Q(consignee=company)
    ).order_by('-created_at')[:20]

    # Construct locations list (Only Company primary address as per user request)
    locations = []
    if company.address_line1:
        locations.append({
            'name': f"Main Office - {company.name}",
            'code': 'HQ',
            'full_address': company.full_address,
            'city': company.city,
            'state': company.state,
            'country': company.country,
            'is_warehouse': False,
            'phone': company.phone,
            'email': company.email
        })

    from apps.inventory.models import Material
    materials = Material.plain_objects.filter(
        Q(tenant=request.user.tenant) | Q(tenant__isnull=True)
    ).filter(
        Q(company=company) | Q(company__isnull=True)
    ).order_by('name')

    documents = company.documents.all()

    context = {
        'company': company,
        'shipments': shipments,
        'orders': orders,
        'locations': locations,
        'materials': materials,
        'available_materials': Material.plain_objects.filter(
            Q(tenant=request.user.tenant) | Q(tenant__isnull=True)
        ).filter(company__isnull=True),
        'documents': documents,
        'history': company.history.all()[:50],  # Get last 50 history records
        'location_form': WarehouseForm(initial={'company': company}),
    }
    return render(request, 'accounts/company_detail.html', context)


@login_required
def company_edit(request, pk):
    """Edit an existing company"""
    company = get_object_or_404(Company.plain_objects, pk=pk)
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES, instance=company, user=request.user)
        if form.is_valid():
            company = form.save()
            geocode_company(company, save=True)
            logger.info(f'Company updated: {company.name} (ID: {pk}) by {request.user}')
            return redirect('accounts:company_detail', pk=pk)
        else:
            logger.warning(f'Company edit form invalid for ID {pk}: {form.errors}')
    else:
        form = CompanyForm(instance=company, user=request.user)
    context = {
        'form': form,
        'company': company,
        'title': f'Edit {company.name}',
        'is_edit': True
    }
    return render(request, 'accounts/company_form.html', context)


@login_required
def company_delete(request, pk):
    """Delete a company"""
    company = get_object_or_404(Company.plain_objects, pk=pk)
    if request.method == 'POST':
        name = company.name
        company.delete()
        logger.info(f'Company deleted: {name} (ID: {pk}) by {request.user}')
        return redirect('accounts:company_list')
    context = {'company': company}
    return render(request, 'accounts/company_confirm_delete.html', context)


@login_required
def company_create(request):
    """Create a new company"""
    if request.method == 'POST':
        # Diagnostic logging to find why materials are missing
        with open('debug_post.txt', 'a') as f:
            f.write(f"\n--- New Company Submission ---\n")
            f.write(f"POST data: {dict(request.POST)}\n")
            f.write(f"Files: {dict(request.FILES)}\n")

        form = CompanyForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            company = form.save(commit=False)
            if hasattr(request.user, 'tenant'):
                company.tenant = request.user.tenant
            company.created_by = request.user
            company.save()
            form.save_m2m() # Guarantee tags and materials are saved
            geocode_company(company, save=True)
            
            # Create a default warehouse location if address is provided
            if company.address_line1 or company.city:
                from apps.inventory.models import Warehouse
                Warehouse.objects.create(
                    name=f"Main Office - {company.name}",
                    code=f"{company.name[:3].upper()}-{company.pk}",
                    address=company.address_line1,
                    city=company.city,
                    state=company.state,
                    country=company.country,
                    postal_code=company.postal_code,
                    company=company,
                    tenant=company.tenant
                )
            
            return redirect('accounts:company_list')
    else:
        # Pre-select company type if passed in URL
        initial_data = {}
        company_type = request.GET.get('type')
        if company_type in [choice[0] for choice in Company.COMPANY_TYPE_CHOICES]:
            initial_data['company_type'] = company_type
        
        form = CompanyForm(initial=initial_data, user=request.user)
        
    context = {
        'form': form,
        'title': 'Add Company',
        'is_edit': False
    }
    return render(request, 'accounts/company_form.html', context)


@login_required
@require_POST
def ajax_help_ticket(request):
    """Create a lightweight support ticket by sending an email."""
    ticket_type = (request.POST.get('ticket_type') or '').strip().lower()
    notify_email = (request.POST.get('notify_email') or '').strip()
    title = (request.POST.get('title') or '').strip()
    description = (request.POST.get('description') or '').strip()
    steps = (request.POST.get('steps') or '').strip()

    if ticket_type not in {'suggestion', 'bug'}:
        return JsonResponse({'success': False, 'message': 'Invalid ticket type.'}, status=400)

    if not notify_email or not title or not description:
        return JsonResponse({'success': False, 'message': 'Please fill all required fields.'}, status=400)

    if ticket_type == 'bug' and not steps:
        return JsonResponse({'success': False, 'message': 'Steps to reproduce are required for bug reports.'}, status=400)

    subject_prefix = 'Suggestion' if ticket_type == 'suggestion' else 'Bug Report'
    subject = f'{subject_prefix}: {title}'
    body_lines = [
        f'Ticket Type: {subject_prefix}',
        f'Raised By: {request.user.get_full_name() or request.user.username}',
        f'Username: {request.user.username}',
        f'Notify Email: {notify_email}',
        '',
        f'Title: {title}',
        '',
        'Description:',
        description,
    ]

    if ticket_type == 'bug':
        body_lines.extend([
            '',
            'Steps to Reproduce:',
            steps,
        ])

    try:
        email = EmailMessage(
            subject=subject,
            body='\n'.join(body_lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=['subham32032@gmail.com'],
            reply_to=[notify_email],
        )
        email.send(fail_silently=False)
    except Exception as exc:
        logger.exception('Failed to send help ticket email: %s', exc)
        return JsonResponse({'success': False, 'message': 'Failed to send ticket email.'}, status=500)

    return JsonResponse({
        'success': True,
        'message': 'Ticket created and email sent successfully.',
    })

@login_required
@require_POST
def company_document_upload(request, pk):
    """AJAX upload for company documents"""
    company = get_object_or_404(Company, pk=pk)
    # Check access
    if request.user.role == 'customer':
        check_company_access(company, request.user)
    
    if request.FILES.get('file'):
        file = request.FILES['file']
        doc_type = request.POST.get('document_type', 'other')
        title = request.POST.get('title', file.name)
        
        document = CompanyDocument.objects.create(
            company=company,
            document_type=doc_type,
            title=title,
            file=file,
            uploaded_by=request.user,
            tenant=company.tenant
        )
        
        return JsonResponse({
            'success': True,
            'document': {
                'id': document.id,
                'title': document.title,
                'type_display': document.get_document_type_display(),
                'url': document.file.url,
                'uploaded_at': document.uploaded_at.strftime('%b %d, %Y'),
                'uploaded_by': document.uploaded_by.get_full_name() or document.uploaded_by.username
            }
        })
    return JsonResponse({'success': False, 'message': 'No file provided'}, status=400)


@login_required
@require_POST
def company_document_delete(request, doc_pk):
    """AJAX delete for company documents"""
    document = get_object_or_404(CompanyDocument, pk=doc_pk)
    
    # Check access
    if request.user.role == 'customer':
        check_company_access(document.company, request.user)
    
    document.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def ajax_associate_material(request, pk):
    """Associate an existing material with a company via AJAX"""
    company = get_object_or_404(Company, pk=pk)
    material_id = request.POST.get('material_id')
    if not material_id:
        return JsonResponse({'success': False, 'message': 'No material selected'}, status=400)
    
    from apps.inventory.models import Material
    material = get_object_or_404(Material, pk=material_id)
    
    # Associate material with company
    material.company = company
    material.save()
    
    # Log History
    from .models import CompanyHistory
    CompanyHistory.objects.create(
        company=company,
        user=request.user,
        action="Added a new Company Material",
        description=f"Associated material {material.name} with the company.",
        icon="fas fa-plus-circle"
    )
    
    return JsonResponse({
        'success': True,
        'material': {
            'id': material.id,
            'name': material.name,
            'type': material.material_type or "—",
            'grade': material.grade or "—",
            'form': material.product_type or "—",
            'description': material.description or ""
        }
    })


@login_required
@require_POST
def ajax_add_contact(request):
    """AJAX create and associate a contact (CustomUser) with a company"""
    company_id = request.POST.get('company_id')
    name = request.POST.get('name')
    email = request.POST.get('email')
    phone = request.POST.get('phone')
    
    if not all([company_id, name, email]):
        return JsonResponse({'success': False, 'message': 'Required fields missing'}, status=400)
    
    company = get_object_or_404(Company, pk=company_id)
    
    # Check if user already exists
    from .models import CustomUser
    if CustomUser.objects.filter(email__iexact=email).exists():
        return JsonResponse({'success': False, 'message': 'A contact with this email already exists.'}, status=400)
    
    # Create simple username from email
    username = email.split('@')[0]
    import uuid
    if CustomUser.objects.filter(username=username).exists():
        username = f"{username}_{str(uuid.uuid4())[:4]}"
        
    try:
        user = CustomUser.objects.create(
            username=username,
            email=email,
            first_name=name.split(' ')[0],
            last_name=' '.join(name.split(' ')[1:]) if ' ' in name else '',
            phone=phone,
            company=company,
            role='customer',
            tenant=company.tenant,
            is_active=True
        )
        
        # Log History
        from .models import CompanyHistory
        CompanyHistory.objects.create(
            company=company,
            user=request.user,
            action="Added a new Contact",
            description=f"Added {user.get_full_name() or user.username} as a contact.",
            icon="fas fa-user-plus"
        )
        
        return JsonResponse({
            'success': True,
            'contact': {
                'id': user.id,
                'name': user.get_full_name() or user.username,
                'email': user.email,
                'phone': user.phone or "(---) --- ----"
            }
        })
    except Exception as e:
        logger.exception('Failed to create contact: %s', e)
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)


@login_required
@require_POST
def ajax_edit_contact(request):
    """AJAX update a contact (CustomUser)"""
    contact_id = request.POST.get('contact_id')
    name = request.POST.get('name')
    email = request.POST.get('email')
    phone = request.POST.get('phone')
    
    if not all([contact_id, name, email]):
        return JsonResponse({'success': False, 'message': 'Required fields missing'}, status=400)
    
    from .models import CustomUser
    contact = get_object_or_404(CustomUser, pk=contact_id)
    
    # Check access (same company or tenant)
    if contact.tenant != request.user.tenant and contact.company.tenant != request.user.tenant:
         return JsonResponse({'success': False, 'message': 'Permission denied'}, status=403)

    try:
        contact.email = email
        contact.first_name = name.split(' ')[0]
        contact.last_name = ' '.join(name.split(' ')[1:]) if ' ' in name else ''
        contact.phone = phone
        contact.save()
        
        # Log History
        from .models import CompanyHistory
        CompanyHistory.objects.create(
            company=contact.company,
            user=request.user,
            action="Changed Contact Details",
            description=f"Updated details for {contact.get_full_name() or contact.username}.",
            icon="fas fa-user-edit"
        )
        
        return JsonResponse({
            'success': True,
            'contact': {
                'id': contact.id,
                'name': contact.get_full_name() or contact.username,
                'email': contact.email,
                'phone': contact.phone or "(---) --- ----"
            }
        })
    except Exception as e:
        logger.exception('Failed to update contact: %s', e)
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)


@login_required
@require_POST
def ajax_archive_contact(request):
    """AJAX archive a contact (set is_contact_archived=True)"""
    import json
    data = json.loads(request.body)
    contact_id = data.get('contact_id')
    
    if not contact_id:
        return JsonResponse({'success': False, 'message': 'Contact ID missing'}, status=400)
    
    from .models import CustomUser
    contact = get_object_or_404(CustomUser, pk=contact_id)
    
    # Check access
    if contact.tenant != request.user.tenant and contact.company.tenant != request.user.tenant:
         return JsonResponse({'success': False, 'message': 'Permission denied'}, status=403)
         
    try:
        contact.is_contact_archived = True
        contact.save()
        
        # Log History
        from .models import CompanyHistory
        CompanyHistory.objects.create(
            company=contact.company,
            user=request.user,
            action="Archived Contact",
            description=f"Archived contact {contact.get_full_name() or contact.username}.",
            icon="fas fa-user-slash"
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        logger.exception('Failed to archive contact: %s', e)
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)


@login_required
@require_POST
def ajax_unarchive_contact(request):
    """AJAX unarchive a contact (set is_contact_archived=False)"""
    import json
    data = json.loads(request.body)
    contact_id = data.get('contact_id')
    
    if not contact_id:
        return JsonResponse({'success': False, 'message': 'Contact ID missing'}, status=400)
    
    from .models import CustomUser
    contact = get_object_or_404(CustomUser, pk=contact_id)
    
    # Check access
    if contact.tenant != request.user.tenant and contact.company.tenant != request.user.tenant:
         return JsonResponse({'success': False, 'message': 'Permission denied'}, status=403)
         
    try:
        contact.is_contact_archived = False
        contact.save()
        
        # Log History
        from .models import CompanyHistory
        CompanyHistory.objects.create(
            company=contact.company,
            user=request.user,
            action="Unarchived Contact",
            description=f"Unarchived contact {contact.get_full_name() or contact.username}.",
            icon="fas fa-user-check"
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        logger.exception('Failed to unarchive contact: %s', e)
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)


@login_required
@require_POST
def ajax_update_company_about(request, pk):
    """AJAX update for company description (About section)"""
    company = get_object_or_404(Company.plain_objects, pk=pk)
    
    # Check access (same company or tenant)
    if not getattr(request.user, 'is_admin', False):
        if request.user.tenant != company.tenant:
             return JsonResponse({'success': False, 'message': 'Permission denied'}, status=403)
             
    description = request.POST.get('description', '')
    company.description = description
    company.save()
    
    # Log History
    from .models import CompanyHistory
    CompanyHistory.objects.create(
        company=company,
        user=request.user,
        action="Updated Company About",
        description=f"Updated the 'About' section for {company.name}.",
        icon="fas fa-edit"
    )
    
    return JsonResponse({'success': True, 'description': company.description})


@login_required
@require_POST
def ajax_update_company_logo(request, pk):
    """Update company logo via AJAX"""
    company = get_object_or_404(Company, pk=pk)
    logo_file = request.FILES.get('logo')

    if logo_file:
        company.logo = logo_file
        company.save()
        return JsonResponse({
            'success': True,
            'message': 'Logo updated successfully.',
            'logo_url': company.logo.url
        })
    return JsonResponse({'success': False, 'message': 'No logo file provided.'})


@login_required
@require_POST
def ajax_remove_company_logo(request, pk):
    """Remove company logo via AJAX"""
    company = get_object_or_404(Company, pk=pk)
    if company.logo:
        company.logo.delete()
        company.save()
        return JsonResponse({
            'success': True,
            'message': 'Logo removed successfully.'
        })
    return JsonResponse({'success': False, 'message': 'No logo to remove.'})

