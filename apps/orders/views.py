from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Q, Case, When, Value, IntegerField
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Order, ManifestItem, Tag, ShippingTerm, PackagingType
from apps.accounts.models import Company
from apps.inventory.models import Warehouse, InventoryItem
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
            return qs.filter(Q(receiver=self.request.user.company) | Q(created_by=self.request.user))
        return filter_by_user_company(qs, self.request.user, company_field='receiver')

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
        
        return context

class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'orders/order_detail.html'
    context_object_name = 'order'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
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
        context['events'] = self.object.events.all()
        
        # Context for Edit Offcanvas
        user_tenant = self.request.user.tenant
        user_company = self.request.user.company
        
        # Show all active companies (tenant-specific + global)
        all_companies = Company.plain_objects.filter(is_active=True).filter(Q(tenant=user_tenant) | Q(tenant__isnull=True))
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
            logger.info(f'Order {order.order_number} status: {old_status} → {order.get_status_display()} by {request.user}')
        
        # ── NEW: Handle Payment Status Update ──────────────────────
        pay_status = request.POST.get('payment_status')
        if pay_status in dict(Order.PAYMENT_STATUS_CHOICES):
            old_pay = order.get_payment_status_display()
            order.payment_status = pay_status
            order.save()
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
            supplier_id=request.POST.get('supplier'),
            receiver_id=request.POST.get('receiver'),
            source_location_id=resolve_location(source_loc_val, request.user),
            destination_location_id=resolve_location(dest_loc_val, request.user),
            total_weight_target=request.POST.get('total_weight_target') or 0,
            freight_cost=request.POST.get('freight_cost') or 0,
            expected_pickup_date=request.POST.get('expected_pickup_date') or None,
            expected_delivery_date=request.POST.get('expected_delivery_date') or None,
            shipping_terms_id=request.POST.get('shipping_terms'),
            representative_id=request.POST.get('representative'),
            status='confirmed', # Default to confirmed for manual entries
            payment_status='pending',
            created_by=request.user,
            tenant=request.user.tenant
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
            qty_to_deduct = float(weights[i]) if i < len(weights) and weights[i] else 0
            
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
                    buy_price=buy_prices[i] if i < len(buy_prices) else 0,
                    buy_price_unit=buy_price_units[i] if i < len(buy_price_units) else "per lbs",
                    sell_price=sell_prices[i] if i < len(sell_prices) else 0,
                    sell_price_unit=sell_price_units[i] if i < len(sell_price_units) else "per lbs",
                    packaging=packagings[i] if i < len(packagings) else "",
                    is_palletized=is_palletized_list[i].lower() == 'true' if i < len(is_palletized_list) else False 
                )
            except Exception as e:
                print(f"Error creating manifest item {i}: {e}")
                continue
        
        # ── NEW: Send email notification to supplier ──────────────────
        try:
            send_order_notification_to_supplier(order, request)
        except Exception as e:
            logger.warning(f'Supplier email failed for order {order.order_number}: {e}')
        # ──────────────────────────────────────────────────────────────

        return redirect('orders:order_detail', pk=order.pk)
    
    logger.info(f'New order creation page accessed by {request.user}')
    
    user_company = request.user.company
    
    # Show all active companies (multitenancy handled by model manager usually, but being explicit)
    # Include both tenant-specific and global companies (where tenant is null)
    company_qs = Company.plain_objects.filter(is_active=True)
    if request.user.tenant:
        company_qs = company_qs.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True))
    
    suppliers = company_qs
    receivers = company_qs
    
    inventory_items = InventoryItem.plain_objects.all()

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
        # Show both tenant-specific and global terms/tags
        'shipping_terms': ShippingTerm.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)),
        'tags': Tag.plain_objects.filter(Q(tenant=request.user.tenant) | Q(tenant__isnull=True)),
        'packaging_types': PackagingType.objects.all(),
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
        
        order.source_location_id = request.POST.get('source_location')
        order.destination_location_id = request.POST.get('destination_location')
        order.po_number = request.POST.get('po_number')
        order.so_number = request.POST.get('so_number')
        order.shipping_terms_id = request.POST.get('shipping_terms')
        order.representative_id = request.POST.get('representative')
        order.freight_cost = request.POST.get('freight_cost') or 0
        order.expected_pickup_date = request.POST.get('expected_pickup_date') or None
        order.expected_delivery_date = request.POST.get('expected_delivery_date') or None
        
        # Handle Tags
        tag_ids = request.POST.getlist('tags')
        if tag_ids:
            order.tags.set(tag_ids)
        else:
            order.tags.clear()
            
        order.save()
        logger.info(f'Order {order.order_number} parameters updated by {request.user}')
        return redirect('orders:order_detail', pk=order.pk)

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
