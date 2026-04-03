from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Q, Case, When, Value, IntegerField
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Order, ManifestItem, Tag, ShippingTerm, PackagingType
from apps.accounts.models import Company
from apps.inventory.models import Warehouse, InventoryItem, Material
from apps.inventory.forms import MaterialForm
from apps.accounts.utils import filter_by_user_company, check_company_access
import logging

logger = logging.getLogger('apps.orders')


class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = 'orders/order_list.html'
    context_object_name = 'orders'

    def get_queryset(self):
        qs = Order.objects.all().order_by('-created_at')
        # Allow access if user is receiver OR the creator of the order
        if self.request.user.role == 'customer' and self.request.user.company:
            qs = qs.filter(Q(receiver=self.request.user.company) | Q(created_by=self.request.user))
        else:
            qs = filter_by_user_company(qs, self.request.user, company_field='receiver')

        # --- Scope Filtering ---
        # Only admins can see 'all' scope. Others default to 'personal'.
        is_admin = getattr(self.request.user, 'is_admin', False)
        default_scope = 'all' if is_admin else 'personal'
        scope = self.request.GET.get('scope', default_scope)
        
        # Enforce restriction
        if not is_admin and scope != 'personal':
            scope = 'personal'
            
        if scope == 'personal':
            qs = qs.filter(created_by=self.request.user)

        # --- Advanced Filtering ---
        statuses = self.request.GET.getlist('status')
        if statuses:
            status_queries = Q()
            for status in statuses:
                if status == 'open':
                    status_queries |= ~Q(status__in=['delivered', 'closed'])
                elif status == 'complete':
                    status_queries |= Q(status__in=['delivered', 'closed'])
                else:
                    status_queries |= Q(status=status)
            qs = qs.filter(status_queries)
            
        supplier_ids = [v for v in self.request.GET.getlist('supplier') if v]
        if supplier_ids:
            qs = qs.filter(supplier_id__in=supplier_ids)
            
        receiver_ids = [v for v in self.request.GET.getlist('receiver') if v]
        if receiver_ids:
            qs = qs.filter(receiver_id__in=receiver_ids)
            
        materials = [v for v in self.request.GET.getlist('material') if v]
        if materials:
            qs = qs.filter(manifest_items__material__in=materials).distinct()
            
        material_types = [v for v in self.request.GET.getlist('material_type') if v]
        if material_types:
            material_names = Material.objects.filter(tenant=self.request.user.tenant, material_type__in=material_types).values_list('name', flat=True)
            qs = qs.filter(manifest_items__material__in=material_names).distinct()
        
        weight_unit = self.request.GET.get('weight_unit', 'lbs')
        
        def to_lbs(val, unit):
            if not val: return None
            try:
                v = float(val)
                if unit == 'kgs': return v * 2.20462
                if unit == 'mt': return v * 2204.62
                if unit == 'st': return v * 2000
                return v
            except: return None

        min_weight = to_lbs(self.request.GET.get('min_weight'), weight_unit)
        if min_weight:
            qs = qs.filter(total_weight_target__gte=min_weight)
            
        max_weight = to_lbs(self.request.GET.get('max_weight'), weight_unit)
        if max_weight:
            qs = qs.filter(total_weight_target__lte=max_weight)
            
        shipping_term_ids = [v for v in self.request.GET.getlist('shipping_term') if v]
        if shipping_term_ids:
            qs = qs.filter(shipping_terms_id__in=shipping_term_ids)
            
        packagings = [v for v in self.request.GET.getlist('packaging') if v]
        if packagings:
            qs = qs.filter(manifest_items__packaging__in=packagings).distinct()
            
        representative_ids = [v for v in self.request.GET.getlist('representative') if v]
        if representative_ids:
            qs = qs.filter(representative_id__in=representative_ids)
            
        tag_ids = [v for v in self.request.GET.getlist('tag') if v]
        if tag_ids:
            qs = qs.filter(tags__id__in=tag_ids)

        # Global Search
        search_query = self.request.GET.get('search')
        if search_query:
            qs = qs.filter(
                Q(order_number__icontains=search_query) |
                Q(po_number__icontains=search_query) |
                Q(so_number__icontains=search_query) |
                Q(supplier__name__icontains=search_query) |
                Q(receiver__name__icontains=search_query)
            ).distinct()

        return qs

    def get_template_names(self):
        if self.request.GET.get('ajax') == '1':
            return ['orders/order_list_partial.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        orders = self.get_queryset()
        
        # Dashboard Analytics
        context['total_orders'] = orders.count()
        context['in_transit_count'] = orders.filter(status='in_transit').count()
        context['pending_payment_count'] = orders.filter(payment_status='pending').count()
        
        # Sum of weight target vs shipped weight
        # Note: We'll use the @property from model in the template, 
        # but for top cards we can do a quick sum here.
        total_target = orders.aggregate(Sum('total_weight_target'))['total_weight_target__sum'] or 0
        context['total_target_weight'] = total_target
        
        # Calculate shipped weight across all orders
        # (This is more complex because it's in a related model)
        shipped_weight = 0
        for o in orders:
            shipped_weight += o.shipped_weight
        context['total_shipped_weight'] = shipped_weight
        
        # --- Context for Advanced Filters Drawer ---
        user_tenant = self.request.user.tenant
        # Companies: use all companies (match order_create behavior)
        all_companies = Company.plain_objects.all().order_by('name')
        
        context['status_choices'] = Order.STATUS_CHOICES
        context['suppliers'] = all_companies
        context['receivers'] = all_companies
        
        # Unique materials from both Material model and existing orders
        m_model = set(Material.objects.all().values_list('name', flat=True))
        m_items = set(ManifestItem.objects.all().values_list('material', flat=True))
        context['materials'] = sorted(list(m_model | m_items))
        
        # Unique material types from Material model
        context['material_types'] = Material.objects.filter(tenant=user_tenant).values_list('material_type', flat=True).distinct().order_by('material_type')
        
        # Packaging types from both PackagingType model and existing orders
        p_model = set(PackagingType.objects.all().values_list('name', flat=True))
        p_items = set(ManifestItem.objects.all().values_list('packaging', flat=True))
        context['packagings'] = sorted(list(p_model | p_items))
        
        context['tags'] = Tag.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
        context['shipping_terms'] = ShippingTerm.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
        context['representatives'] = get_user_model().objects.filter(tenant=user_tenant, is_active=True).order_by('first_name', 'username')
        
        # Preserve filter states to pre-fill the drawer inputs
        context['filters'] = {
            'status': self.request.GET.get('status', ''),
            'status_list': self.request.GET.getlist('status'),
            'supplier_list': self.request.GET.getlist('supplier'),
            'receiver_list': self.request.GET.getlist('receiver'),
            'material_list': self.request.GET.getlist('material'),
            'material_type_list': self.request.GET.getlist('material_type'),
            'min_weight': self.request.GET.get('min_weight', ''),
            'max_weight': self.request.GET.get('max_weight', ''),
            'weight_unit': self.request.GET.get('weight_unit', 'lbs'),
            'shipping_term_list': self.request.GET.getlist('shipping_term'),
            'packaging_list': self.request.GET.getlist('packaging'),
            'representative_list': self.request.GET.getlist('representative'),
            'tag_list': self.request.GET.getlist('tag'),
            'search': self.request.GET.get('search', ''),
            'scope': self.request.GET.get('scope', 'all'),
        }
        
        return context

class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'orders/order_detail.html'
    context_object_name = 'order'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        
        # Trigger automatic 'overdue' check (Net 30)
        obj.check_payment_status()
        
        # Allow creator to see the order even if they are not the receiver
        if obj.created_by == self.request.user:
            return obj
        check_company_access(obj.receiver, self.request.user)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['manifest_items'] = self.object.manifest_items.all()
        context['shipments'] = self.object.shipments.all()
        context['invoices'] = self.object.invoices.all()
        context['events'] = self.object.events.filter(
            Q(event_type__in=['order_created', 'shipment_created', 'note_added', 'document_added', 'payment_status_updated']) |
            Q(event_type='status_updated', description__icontains='Order status is now')
        )
        context['documents'] = self.object.documents.all()
        
        # Context for Edit Offcanvas
        user_tenant = self.request.user.tenant
        user_company = self.request.user.company
        assign_company = user_company or Company.objects.filter(tenant=user_tenant).first()
        
        # Show companies (filtered by creator OR user's own company unless admin)
        all_companies = Company.plain_objects.filter(is_active=True).filter(Q(tenant=user_tenant) | Q(tenant__isnull=True))
        if not getattr(self.request.user, 'is_admin', False):
            if user_company:
                all_companies = all_companies.filter(Q(created_by=self.request.user) | Q(pk=user_company.pk))
            else:
                all_companies = all_companies.filter(created_by=self.request.user)
        
        context['suppliers'] = all_companies
        context['receivers'] = all_companies
        
        # Locations (Prioritize user's company and filter by tenant)
        warehouses = Warehouse.plain_objects.filter(tenant=user_tenant)
        if user_company:
            warehouses = warehouses.annotate(
                is_my_company=Case(
                    When(company=user_company, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField()
                )
            ).order_by('-is_my_company', 'name')
        context['warehouses'] = warehouses
        
        # Show ONLY the currently selected shipping term
        if self.object.shipping_terms_id:
            context['shipping_terms'] = ShippingTerm.plain_objects.filter(pk=self.object.shipping_terms_id)
        else:
            context['shipping_terms'] = ShippingTerm.plain_objects.none()
        
        # Show ONLY the currently selected tags
        context['tags'] = self.object.tags.all()
        
        # Show ONLY the currently selected representative
        if self.object.representative:
            context['team_members'] = get_user_model().objects.filter(pk=self.object.representative.pk)
        else:
            context['team_members'] = get_user_model().objects.none()
            
        # Context for Add Shipment Offcanvas
        context['all_tags'] = Tag.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
        context['all_shipping_terms'] = ShippingTerm.plain_objects.filter(Q(tenant=user_tenant) | Q(tenant__isnull=True)).order_by('name')
        context['all_representatives'] = get_user_model().objects.filter(tenant=user_tenant, is_active=True).order_by('first_name', 'username')
            
        inventory_items_qs = InventoryItem.plain_objects.filter(
            company=self.object.supplier,
            tenant=self.object.tenant
        )

        # Calculation for remaining manifest balance
        from apps.shipments.models import ShipmentItem
        shipped_weights = ShipmentItem.objects.filter(
            shipment__order=self.object
        ).values('material_name').annotate(total_shipped=Sum('weight'))
        
        shipped_map = {sw['material_name']: sw['total_shipped'] for sw in shipped_weights}
        manifest_items = list(context['manifest_items'])
        manifest_map = {mi.material: mi.weight for mi in manifest_items}
        
        # If there's only one manifest item, use the larger of manifest weight or total target
        if len(manifest_items) == 1:
            mi = manifest_items[0]
            manifest_map[mi.material] = max(mi.weight, self.object.total_weight_target)
        
        inventory_items = list(inventory_items_qs)
        for item in inventory_items:
            m_weight = manifest_map.get(item.product_name, 0)
            if m_weight > 0:
                s_weight = shipped_map.get(item.product_name, 0)
                # Use Decimal for precise subtraction
                from decimal import Decimal
                diff = Decimal(str(m_weight)) - Decimal(str(s_weight))
                item.order_balance = max(0, diff)
            else:
                item.order_balance = None
        
        context['inventory_items'] = inventory_items
        context['assign_company'] = assign_company
        context['packaging_types'] = PackagingType.objects.all()
        
        # --- Context for Contact Pre-filling ---
        # Fetch unique contacts from existing shipments of this order
        shipments = self.object.shipments.all().order_by('-created_at')
        
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

        context['previous_pickup_contacts'] = pickup_contacts
        context['previous_delivery_contacts'] = delivery_contacts
        context['material_form'] = MaterialForm()
        
        return context

@login_required
def order_update_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        status = request.POST.get('status')
        
        # Handle simplified workflow: map "open" and "complete" to existing statuses
        if status == 'open':
            status = 'confirmed'  # Map "open" to "confirmed" for backend
        elif status == 'complete':
            status = 'delivered'  # Map "complete" to "delivered" for backend
        
        if status in dict(Order.STATUS_CHOICES):
            old_status = order.get_status_display()
            order.status = status
            order.save()
            
            # Create Lifecycle Event
            from .models import OrderEvent
            OrderEvent.objects.create(
                order=order,
                event_type='status_updated',
                description=f"Status updated from {old_status} to {order.get_status_display()}",
                created_by=request.user
            )
            
            logger.info(f'Order {order.order_number} status: {old_status} → {order.get_status_display()} by {request.user}')
        
        # ── NEW: Handle Payment Status Update ──────────────────────
        pay_status = request.POST.get('payment_status')
        if pay_status in dict(Order.PAYMENT_STATUS_CHOICES):
            old_pay = order.get_payment_status_display()
            order.payment_status = pay_status
            order.save()

            # Create Lifecycle Event
            from .models import OrderEvent
            OrderEvent.objects.create(
                order=order,
                event_type='payment_status_updated',
                description=f"Payment status updated from {old_pay} to {order.get_payment_status_display()}",
                created_by=request.user
            )

            logger.info(f'Order {order.order_number} payment: {old_pay} → {order.get_payment_status_display()} by {request.user}')
        # ──────────────────────────────────────────────────────────
    return redirect('orders:order_detail', pk=pk)

@login_required
def order_create(request):
    if request.method == 'POST':
        # Handle dynamic location creation for "my company address"
        source_loc_val = request.POST.get('source_location')
        dest_loc_val = request.POST.get('destination_location')
        
        print(f"\n--- ORDER CREATE DEBUG ---")
        print(f"Original Source: {source_loc_val}")
        print(f"Original Dest: {dest_loc_val}")
        
        def resolve_location(val, user):
            if not val: return None
            if str(val).startswith('temp_addr_') or str(val).startswith('http') or len(str(val)) > 10:
                print(f"Resolving dynamic address: {val}")
                company = user.company
                if not company: 
                    print("User has no company!")
                    return None
                
                raw_address = str(val).replace('temp_addr_', '')[:200]
                
                # Generate a unique code to avoid IntegrityError if a location with MAIN-<id> already exists
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
                print(f"Resolved to Warehouse ID: {hq.id} (Created: {created})")
                return hq.id
            return val

        # Generate a unique order number on the backend
        import time, random
        order_number = f"STH-O-{request.user.id}-{int(time.time())}-{random.randint(1000, 9999)}"

        # Create the order
        order = Order.objects.create(
            order_number=order_number,
            po_number=request.POST.get('po_number'),
            so_number=request.POST.get('so_number'),
            supplier_id=request.POST.get('supplier') or None,
            receiver_id=request.POST.get('receiver') or None,
            source_location_id=resolve_location(source_loc_val, request.user) or None,
            destination_location_id=resolve_location(dest_loc_val, request.user) or None,
            total_weight_target=request.POST.get('total_weight_target') or 0,
            total_weight_unit=request.POST.get('total_weight_unit') or 'lbs',
            freight_cost=request.POST.get('freight_cost') or 0,
            expected_pickup_date=request.POST.get('expected_pickup_date') or None,
            expected_delivery_date=request.POST.get('expected_delivery_date') or None,
            shipping_terms_id=request.POST.get('shipping_terms') or None,
            representative_id=request.POST.get('representative') or None,
            status='confirmed', # Default to confirmed for manual entries
            payment_status='pending',
            created_by=request.user,
            tenant=request.user.tenant
        )
        
        # Handle Tags (support dynamic creation)
        tag_input = request.POST.getlist('tags')
        tag_ids = []
        for val in tag_input:
            # Only treat as existing ID if it's numeric AND exists in DB
            if val.isdigit() and Tag.objects.filter(id=val, tenant=request.user.tenant).exists():
                tag_ids.append(val)
            elif val.strip():
                # Treat as a new tag name (even if numeric)
                tag, _ = Tag.objects.get_or_create(tenant=request.user.tenant, name=val.strip())
                tag_ids.append(tag.id)
        order.tags.set(tag_ids)
        
        # Create Lifecycle Event
        from .models import OrderEvent
        OrderEvent.objects.create(
            order=order,
            event_type='order_created',
            description=f"Order #{order.order_number} was created.",
            created_by=request.user
        )
        
        # Handle Manifest Items
        from itertools import zip_longest
        
        materials = request.POST.getlist('material[]')
        weights = request.POST.getlist('weight[]')
        weight_units = request.POST.getlist('weight_unit[]')
        buy_prices = request.POST.getlist('buy_price[]')
        buy_price_units = request.POST.getlist('buy_price_unit[]')
        sell_prices = request.POST.getlist('sell_price[]')
        sell_price_units = request.POST.getlist('sell_price_unit[]')
        packagings = request.POST.getlist('packaging[]')
        is_palletized_list = request.POST.getlist('is_palletized_h[]')
        
        for i in range(len(materials)):
            if not materials[i]:
                continue
                
            material_name = materials[i]
            
            # Robustly parse weight and prices (handle empty strings)
            raw_weight = weights[i] if i < len(weights) else ""
            raw_buy = buy_prices[i] if i < len(buy_prices) else ""
            raw_sell = sell_prices[i] if i < len(sell_prices) else ""
            
            qty_to_deduct = float(raw_weight) if raw_weight and str(raw_weight).strip() else 0
            buy_price_val = raw_buy if raw_buy and str(raw_buy).strip() else 0
            sell_price_val = raw_sell if raw_sell and str(raw_sell).strip() else 0
            
            # ── NEW: Deduct Stock if material is an ID ────────────────
            try:
                # Check if materials[i] is an ID (integer)
                if materials[i].isdigit():
                    inv_item = InventoryItem.plain_objects.get(pk=materials[i])
                    material_name = inv_item.product_name # Use product name for manifest
                    
                    # Deduct stock
                    if qty_to_deduct > 0:
                        inv_item.quantity = max(0, inv_item.quantity - int(qty_to_deduct))
                        inv_item.save()
                        logger.info(f"Deducted {qty_to_deduct} from {inv_item.product_name}. New stock: {inv_item.quantity}")
                        
                        # ── NEW: Trigger Low Stock Notification ───────────
                        if inv_item.quantity <= 10:
                            send_low_stock_notification(inv_item, request)
                        # ──────────────────────────────────────────────────
            except Exception as e:
                logger.warning(f"Stock deduction failed for item {materials[i]}: {e}")
            # ──────────────────────────────────────────────────────────

            try:
                ManifestItem.objects.create(
                    order=order,
                    material=material_name,
                    weight=qty_to_deduct,
                    weight_unit=weight_units[i] if i < len(weight_units) else "lbs",
                    buy_price=buy_price_val,
                    buy_price_unit=buy_price_units[i] if i < len(buy_price_units) else "per lbs",
                    sell_price=sell_price_val,
                    sell_price_unit=sell_price_units[i] if i < len(sell_price_units) else "per lbs",
                    packaging=packagings[i] if i < len(packagings) else "",
                    is_palletized=is_palletized_list[i].lower() == 'true' if i < len(is_palletized_list) else False 
                )
            except Exception as e:
                logger.error(f"Error creating manifest item {i} ({material_name}): {e}")
                continue
        
        # ── NEW: Send email notification to supplier ──────────────────
        try:
            send_order_notification_to_supplier(order, request)
        except Exception as e:
            logger.warning(f'Supplier email failed for order {order.order_number}: {e}')
        # ──────────────────────────────────────────────────────────────

        return redirect('orders:order_detail', pk=order.pk)
    
    logger.info(f'New order creation page accessed by {request.user}')
    
    # ── NEW: Handle Copy Order ────────────────────────────────────────
    copy_id = request.GET.get('copy_id')
    copied_order = None
    copied_items = []
    if copy_id:
        copied_order = get_object_or_404(Order, pk=copy_id)
        # Verify access to the source order
        if copied_order.tenant != request.user.tenant:
            copied_order = None
        else:
            copied_items = copied_order.manifest_items.all()
            logger.info(f"Pre-filling New Order form from Order {copied_order.order_number} (Copy ID: {copy_id})")
    # ──────────────────────────────────────────────────────────────────

    user_company = request.user.company
    assign_company = user_company or Company.objects.filter(tenant=request.user.tenant).first()
    
    # Filter companies by creator OR user's own company unless admin
    company_qs = Company.plain_objects.all()
    if not getattr(request.user, 'is_admin', False):
        if user_company:
            company_qs = company_qs.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            company_qs = company_qs.filter(created_by=request.user)
    
    suppliers = company_qs
    receivers = company_qs
    
    if not getattr(request.user, 'is_admin', False):
        inventory_items = InventoryItem.plain_objects.filter(
            Q(company__in=company_qs) | Q(warehouse__company__in=company_qs),
            tenant=request.user.tenant
        ).distinct()
    else:
        inventory_items = InventoryItem.plain_objects.filter(tenant=request.user.tenant)

    # Show all warehouses in tenant, prioritize user's company
    from django.db.models import Case, When, IntegerField
    warehouses = Warehouse.plain_objects.all().annotate(
        priority=Case(
            When(company=user_company, then=0),
            default=1,
            output_field=IntegerField(),
        )
    ).order_by('priority', 'name')

    context = {
        'suppliers': suppliers,
        'receivers': receivers,
        'warehouses': warehouses,
        'inventory_items': inventory_items,
        'assign_company': assign_company,
        'copied_order': copied_order,
        'copied_items': copied_items,
        # Show both tenant-specific and global terms/tags
        'shipping_terms': ShippingTerm.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)),
        'tags': Tag.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)),
        'team_members': get_user_model().objects.filter(tenant=request.user.tenant),
        'packaging_types': PackagingType.objects.all(),
        'material_form': MaterialForm(),
    }
    return render(request, 'orders/order_form.html', context)


@login_required
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    # Check if we can change supplier/receiver (lock if shipments exist)
    can_change_parties = not order.shipments.exists()

    if request.method == 'POST':
        if can_change_parties:
            order.supplier_id = request.POST.get('supplier')
            order.receiver_id = request.POST.get('receiver')
        
        order.source_location_id = request.POST.get('source_location') or None
        order.destination_location_id = request.POST.get('destination_location') or None
        order.po_number = request.POST.get('po_number')
        order.so_number = request.POST.get('so_number')
        order.shipping_terms_id = request.POST.get('shipping_terms') or None
        order.representative_id = request.POST.get('representative') or None
        order.freight_cost = request.POST.get('freight_cost') or 0
        order.total_weight_target = request.POST.get('total_weight_target') or 0
        order.total_weight_unit = request.POST.get('total_weight_unit') or 'lbs'
        order.expected_pickup_date = request.POST.get('expected_pickup_date') or None
        order.expected_delivery_date = request.POST.get('expected_delivery_date') or None
        
        # Handle Tags (support dynamic creation)
        tag_input = request.POST.getlist('tags')
        if tag_input:
            tag_ids = []
            for val in tag_input:
                # Only treat as existing ID if it's numeric AND exists in DB
                if val.isdigit() and Tag.objects.filter(id=val, tenant=request.user.tenant).exists():
                    tag_ids.append(val)
                elif val.strip():
                    # Treat as a new tag name (even if numeric)
                    tag, _ = Tag.objects.get_or_create(tenant=request.user.tenant, name=val.strip())
                    tag_ids.append(tag.id)
            order.tags.set(tag_ids)
        else:
            order.tags.clear()
            
        order.save()
        
        # Create Lifecycle Event
        from .models import OrderEvent
        OrderEvent.objects.create(
            order=order,
            event_type='status_updated',
            description="Order parameters (supplier, receiver, or logistics) were updated.",
            created_by=request.user
        )
        
        logger.info(f'Order {order.order_number} parameters updated by {request.user}')
        
        # ── NEW: Return PDF after saving in Edit Order ────────────────
        return order_purchase_order_pdf(request, pk)

    # For AJAX/Offcanvas pre-fill if needed, but here we just redirect back 
    # since the offcanvas is embedded in the detail page.
    return redirect('orders:order_detail', pk=order.pk)


# ══════════════════════════════════════════════════════════════════
# NEW: Supplier Order Email Notification
# ══════════════════════════════════════════════════════════════════
def send_order_notification_to_supplier(order, request):
    """
    Sends a professional HTML email to the supplier when a new order is created.
    Silently skips if supplier has no email address.
    """
    from django.core.mail import send_mail
    from django.conf import settings
    from django.template.loader import render_to_string

    supplier = order.supplier
    if not supplier or not supplier.email:
        logger.info(f'Order {order.order_number}: Supplier has no email — skipping notification.')
        return

    manifest_items = order.manifest_items.all()

    # Prepare items data for template
    items_data = []
    for item in manifest_items:
        # Fetch current stock for this item
        try:
            inv_item = InventoryItem.objects.filter(
                product_name=item.material, 
                warehouse__tenant=order.tenant
            ).first()
            available = inv_item.quantity if inv_item else 0
        except Exception:
            available = 0

        # Styles for template
        is_over = float(item.weight) > float(available)
        items_data.append({
            'material': item.material,
            'weight': item.weight,
            'weight_unit': item.weight_unit,
            'available': available,
            'buy_price': item.buy_price,
            'buy_price_unit': item.buy_price_unit,
            'stock_color': "#dc2626" if is_over else "#16a34a",
            'warning_style': "background:#fffbeb;" if is_over else ""
        })

    def _fmt_date(val):
        if not val:
            return '—'
        if hasattr(val, 'strftime'):
            return val.strftime('%d %b %Y')
        try:
            from datetime import datetime
            return datetime.strptime(str(val), '%Y-%m-%d').strftime('%d %b %Y')
        except Exception:
            return str(val)

    pickup   = _fmt_date(order.expected_pickup_date)
    delivery = _fmt_date(order.expected_delivery_date)
    receiver_name = order.receiver.name if order.receiver else '—'
    from_company  = request.user.company.name if request.user.company else 'FreightPro'

    # Context for template
    context = {
        'order': order,
        'supplier': supplier,
        'receiver_name': receiver_name,
        'from_company': from_company,
        'pickup': pickup,
        'delivery': delivery,
        'items': items_data,
    }

    # Render HTML from template file
    html_message = render_to_string('emails/supplier_order_notification.html', context)

    plain_message = (
        f"New Purchase Order: {order.order_number}\n"
        f"Supplier: {supplier.name}\n"
        f"Receiver: {receiver_name}\n"
        f"Pickup: {pickup} | Delivery: {delivery}\n"
        f"Items: {len(items_data)} item(s)\n"
    )

    send_mail(
        subject=f"New Purchase Order #{order.order_number} — {from_company}",
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[supplier.email],
        html_message=html_message,
        fail_silently=True,
    )
    logger.info(f'Order {order.order_number}: Supplier notification email sent to {supplier.email}')


def send_low_stock_notification(item, request):
    """
    Sends a professional HTML email when stock drops to 10 or less.
    Routes to: Warehouse Email > Company Email > Tenant Admin.
    """
    from django.core.mail import send_mail
    from django.conf import settings
    from django.template.loader import render_to_string
    from django.contrib.auth import get_user_model

    # 1. Determine Recipient
    recipient_email = None
    
    # Priority A: Warehouse Email
    if item.warehouse and item.warehouse.email:
        recipient_email = item.warehouse.email
        logger.info(f"Low stock alert for {item.product_name}: Using Warehouse email {recipient_email}")
    
    # Priority B: Company Email
    if not recipient_email and item.warehouse and item.warehouse.company and item.warehouse.company.email:
        recipient_email = item.warehouse.company.email
        logger.info(f"Low stock alert for {item.product_name}: Using Company email {recipient_email}")
        
    # Priority C: Tenant Admin Email
    if not recipient_email and item.tenant:
        User = get_user_model()
        admin_user = User.objects.filter(tenant=item.tenant, role='admin').first()
        if admin_user and admin_user.email:
            recipient_email = admin_user.email
            logger.info(f"Low stock alert for {item.product_name}: Using Admin email {recipient_email}")

    if not recipient_email:
        logger.warning(f"Low stock alert for {item.product_name}: No recipient email found.")
        return

    # 2. Prepare Context
    from_company = request.user.company.name if request.user and request.user.company else 'FreightPro'
    dashboard_url = request.build_absolute_uri('/') # Link to landing/dashboard
    
    context = {
        'item': item,
        'from_company': from_company,
        'dashboard_url': dashboard_url,
    }

    # 3. Render and Send
    try:
        html_message = render_to_string('emails/low_stock_notification.html', context)
        plain_message = f"Alert: Low stock for {item.product_name}. Current quantity: {item.quantity} {item.unit_of_measure}."
        
        send_mail(
            subject=f"⚠️ Low Stock Alert: {item.product_name} at {item.warehouse.name}",
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=True,
        )
        logger.info(f"Low stock notification sent for {item.product_name} to {recipient_email}")
    except Exception as e:
        logger.error(f"Failed to send low stock notification for {item.product_name}: {e}")

@login_required
def order_purchase_order_pdf(request, pk):
    """
    Generate a Purchase Order PDF using ReportLab.
    Accepts POST data for custom instructions, payment terms, and item descriptions.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from io import BytesIO
    from django.http import FileResponse

    order = get_object_or_404(Order, pk=pk)
    # Check access (similar to OrderDetailView)
    if order.created_by != request.user:
        check_company_access(order.receiver, request.user)

    manifest_items = order.manifest_items.all()

    # Get custom data from POST
    file_name = request.POST.get('file_name', f"{order.order_number}_PO.pdf")
    po_number_override = request.POST.get('po_number', order.order_number)
    payment_terms = request.POST.get('payment_terms', 'Net 30')
    instructions = request.POST.get('instructions', '')
    include_descriptions = request.POST.get('include_descriptions') == 'on'

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor('#0055aa')
    light_gray = colors.HexColor('#f8f9fa')
    border_color = colors.HexColor('#dee2e6')

    # Custom Styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=24, textColor=primary_color, fontName='Helvetica-Bold')
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=8, textColor=colors.grey, fontName='Helvetica-Bold', textTransform='uppercase')
    normal_style = ParagraphStyle('Normal2', parent=styles['Normal'], fontSize=10, leading=14)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', leading=14)
    right_style = ParagraphStyle('Right', parent=styles['Normal'], fontSize=10, alignment=TA_RIGHT)
    
    elements = []

    # --- Header ---
    header_data = [
        [Paragraph("PURCHASE ORDER", title_style), Paragraph(f"<b>PO #:</b> {po_number_override}<br/><b>Date:</b> {timezone.now().strftime('%Y-%m-%d')}", right_style)]
    ]
    header_table = Table(header_data, colWidths=[110*mm, 70*mm])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'BOTTOM'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0)]))
    elements.append(header_table)
    elements.append(Spacer(1, 5*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=primary_color))
    elements.append(Spacer(1, 10*mm))

    # --- Vendor & Delivery Details ---
    vendor_info = [
        Paragraph("VENDOR", label_style),
        Paragraph(order.supplier.name, bold_style),
        Paragraph(order.supplier.full_address, normal_style),
    ]
    
    ship_to_info = [
        Paragraph("SHIP TO", label_style),
        Paragraph(order.receiver.name, bold_style),
        Paragraph(order.destination_location.display_name if order.destination_location else order.receiver.full_address, normal_style),
    ]
    
    addresses_data = [[vendor_info, ship_to_info]]
    addresses_table = Table(addresses_data, colWidths=[90*mm, 90*mm])
    addresses_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0)]))
    elements.append(addresses_table)
    elements.append(Spacer(1, 10*mm))

    # --- Order Terms ---
    terms_data = [
        [Paragraph("PAYMENT TERMS", label_style), Paragraph("SHIPPING METHOD", label_style), Paragraph("EXPECTED DATE", label_style)],
        [Paragraph(f"{payment_terms} Days", normal_style), Paragraph(order.shipping_terms.name if order.shipping_terms else "Standard", normal_style), Paragraph(order.expected_pickup_date.strftime('%Y-%m-%d') if order.expected_pickup_date else "-", normal_style)]
    ]
    terms_table = Table(terms_data, colWidths=[60*mm, 60*mm, 60*mm])
    terms_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), light_gray),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(terms_table)
    elements.append(Spacer(1, 10*mm))

    # --- Item Table ---
    item_header = [Paragraph("ITEM / MATERIAL", label_style), Paragraph("QTY", label_style), Paragraph("UNIT", label_style), Paragraph("UNIT PRICE", label_style), Paragraph("TOTAL", label_style)]
    table_data = [item_header]
    
    from decimal import Decimal
    total_amount = Decimal('0')
    for item in manifest_items:
        # Get custom description from POST
        custom_desc = request.POST.get(f'item_desc_{item.id}', '')
        item_text = f"<b>{item.material}</b>"
        if include_descriptions and custom_desc:
            item_text += f"<br/><font size='8' color='grey'>{custom_desc}</font>"
            
        row_total = item.weight * item.buy_price
        total_amount += row_total
        
        table_data.append([
            Paragraph(item_text, normal_style),
            Paragraph(f"{item.weight:,.2f}", normal_style),
            Paragraph(item.weight_unit, normal_style),
            Paragraph(f"${item.buy_price:,.4f}", normal_style),
            Paragraph(f"${row_total:,.2f}", right_style),
        ])

    items_table = Table(table_data, colWidths=[80*mm, 25*mm, 20*mm, 30*mm, 25*mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(items_table)

    # --- Totals ---
    totals_data = [
        ['', '', '', Paragraph("<b>TOTAL</b>", right_style), Paragraph(f"<b>${total_amount:,.2f}</b>", right_style)]
    ]
    totals_table = Table(totals_data, colWidths=[80*mm, 25*mm, 20*mm, 30*mm, 25*mm])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (3,0), (4,0), 'RIGHT'),
        ('GRID', (3,0), (4,0), 0.5, border_color),
        ('BACKGROUND', (3,0), (4,0), light_gray),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 10*mm))

    # --- Instructions ---
    if instructions:
        elements.append(Paragraph("SPECIAL INSTRUCTIONS", label_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(instructions, normal_style))
        elements.append(Spacer(1, 10*mm))

    # --- Footer ---
    elements.append(Spacer(1, 20*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 2*mm))
    elements.append(Paragraph("Authorized Signature: ___________________________", normal_style))
    elements.append(Spacer(1, 5*mm))
    elements.append(Paragraph("Thank you for your business!", ParagraphStyle('Center', parent=styles['Normal'], alignment=TA_CENTER, textColor=colors.grey)))

    doc.build(elements)
    buffer.seek(0)
    
    if not file_name.endswith('.pdf'):
        file_name += '.pdf'
        
        
    # Create Lifecycle Event
    from .models import OrderEvent
    OrderEvent.objects.create(
        order=order,
        event_type='document_added', # PDF generation counts as document activity
        description=f"Purchase Order PDF generated: {file_name}",
        created_by=request.user
    )
        
    return FileResponse(buffer, as_attachment=True, filename=file_name)

@login_required
def order_add_item(request, pk):
    """
    Adds one or more manifest items to an existing order.
    Logic mirrored from order_create.
    """
    order = get_object_or_404(Order, pk=pk)
    
    if request.method == 'POST':
        materials = request.POST.getlist('material[]')
        weights = request.POST.getlist('weight[]')
        weight_units = request.POST.getlist('weight_unit[]')
        buy_prices = request.POST.getlist('buy_price[]')
        buy_price_units = request.POST.getlist('buy_price_unit[]')
        sell_prices = request.POST.getlist('sell_price[]')
        sell_price_units = request.POST.getlist('sell_price_unit[]')
        packagings = request.POST.getlist('packaging[]')
        is_palletized_list = request.POST.getlist('is_palletized_h[]')

        for i in range(len(materials)):
            if not materials[i]:
                continue
                
            material_name = materials[i]
            
            # Robustly parse weight and prices
            raw_weight = weights[i] if i < len(weights) else ""
            raw_buy = buy_prices[i] if i < len(buy_prices) else ""
            raw_sell = sell_prices[i] if i < len(sell_prices) else ""
            
            qty_to_deduct = float(raw_weight) if raw_weight and str(raw_weight).strip() else 0
            buy_price_val = raw_buy if raw_buy and str(raw_buy).strip() else 0
            sell_price_val = raw_sell if raw_sell and str(raw_sell).strip() else 0
            
            # Deduct stock if material is an ID
            try:
                if materials[i].isdigit():
                    inv_item = InventoryItem.plain_objects.get(pk=materials[i])
                    material_name = inv_item.product_name
                    
                    if qty_to_deduct > 0:
                        inv_item.quantity = max(0, inv_item.quantity - int(qty_to_deduct))
                        inv_item.save()
                        
                        if inv_item.quantity <= 10:
                            send_low_stock_notification(inv_item, request)
            except Exception as e:
                logger.warning(f"Stock deduction failed for item {materials[i]}: {e}")

            try:
                ManifestItem.objects.create(
                    order=order,
                    material=material_name,
                    weight=qty_to_deduct,
                    weight_unit=weight_units[i] if i < len(weight_units) else "lbs",
                    buy_price=buy_price_val,
                    buy_price_unit=buy_price_units[i] if i < len(buy_price_units) else "per lbs",
                    sell_price=sell_price_val,
                    sell_price_unit=sell_price_units[i] if i < len(sell_price_units) else "per lbs",
                    packaging=packagings[i] if i < len(packagings) else "",
                    is_palletized=is_palletized_list[i].lower() == 'true' if i < len(is_palletized_list) else False 
                )
            except Exception as e:
                logger.error(f"Error creating manifest item {i} ({material_name}): {e}")
                continue
                
                
        # Create Lifecycle Event for added items
        from .models import OrderEvent
        OrderEvent.objects.create(
            order=order,
            event_type='note_added', # or status_updated if we want to be generic
            description=f"{len(materials)} manifest item(s) added to the order.",
            created_by=request.user
        )
                
        logger.info(f"New manifest items added to Order {order.order_number} by {request.user}")
    
    return redirect('orders:order_detail', pk=pk)

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import OrderDocument

@login_required
@require_POST
def order_upload_document(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No file uploaded'}, status=400)
        
    try:
        file_obj = request.FILES['file']
        
        doc = OrderDocument.objects.create(
            order=order,
            title=file_obj.name,
            file=file_obj,
            uploaded_by=request.user
        )
        
        # Create Lifecycle Event
        from .models import OrderEvent
        OrderEvent.objects.create(
            order=order,
            event_type='document_added',
            description=f"Document uploaded: {doc.title}",
            created_by=request.user
        )
        
        return JsonResponse({
            'success': True,
            'document': {
                'id': doc.id,
                'title': doc.title,
                'url': doc.file.url,
                'uploaded_by': doc.uploaded_by.get_full_name() or doc.uploaded_by.username,
                'uploaded_at': doc.uploaded_at.strftime('%b %d, %Y')
            }
        })
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def order_add_note(request, pk):
    """
    AJAX view to add a note/comment to an order's history.
    """
    order = get_object_or_404(Order, pk=pk)
    
    # Check access
    if order.created_by != request.user:
        check_company_access(order.receiver, request.user)
        
    note_content = request.POST.get('note', '').strip()
    
    if not note_content:
        return JsonResponse({'success': False, 'error': 'Note content cannot be empty'}, status=400)
    
    try:
        from .models import OrderEvent
        event = OrderEvent.objects.create(
            order=order,
            event_type='note_added',
            description=note_content,
            created_by=request.user
        )
        
        return JsonResponse({
            'success': True,
            'event': {
                'id': event.id,
                'type_display': event.get_event_type_display(),
                'description': event.description,
                'created_at_display': event.created_at.strftime('%b %d, %Y %H:%M'),
                'created_at_relative': "just now"
            }
        })
    except Exception as e:
        logger.error(f"Error adding note to order {pk}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def order_edit_manifest_item(request, item_pk):
    """
    Update a single manifest item from the order detail page.
    """
    from .models import ManifestItem, OrderEvent
    item = get_object_or_404(ManifestItem, pk=item_pk)
    
    # Check access
    if item.order.tenant != request.user.tenant:
        return redirect('orders:order_list')
        
    try:
        item.weight = request.POST.get('weight') or item.weight
        item.weight_unit = request.POST.get('weight_unit') or item.weight_unit
        item.buy_price = request.POST.get('buy_price') or item.buy_price
        item.buy_price_unit = request.POST.get('buy_price_unit') or item.buy_price_unit
        item.sell_price = request.POST.get('sell_price') or item.sell_price
        item.sell_price_unit = request.POST.get('sell_price_unit') or item.sell_price_unit
        item.packaging = request.POST.get('packaging') or ""
        item.is_palletized = request.POST.get('is_palletized') == 'on' or request.POST.get('is_palletized') == 'true'
        item.save()
        
        # Create Lifecycle Event
        OrderEvent.objects.create(
            order=item.order,
            event_type='status_updated',
            description=f"Manifest item '{item.material}' updated.",
            created_by=request.user
        )
        
        logger.info(f"Manifest item {item_pk} updated by {request.user}")
    except Exception as e:
        logger.error(f"Error updating manifest item {item_pk}: {e}")
        
    return redirect('orders:order_detail', pk=item.order.pk)
