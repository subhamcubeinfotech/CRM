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
        check_company_access(obj.receiver, self.request.user)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['manifest_items'] = self.object.manifest_items.all()
        context['shipments'] = self.object.shipments.all()
        context['invoices'] = self.object.invoices.all()
        
        # Context for Edit Offcanvas
        user_tenant = self.request.user.tenant
        user_company = self.request.user.company
        
        # Filter companies by tenant
        context['suppliers'] = Company.objects.filter(tenant=user_tenant, company_type='vendor')
        context['receivers'] = Company.objects.filter(tenant=user_tenant, company_type='customer')
        
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
                
                # Check if Main Office location already exists to avoid duplicates
                hq, created = Warehouse.objects.get_or_create(
                    company=company,
                    tenant=company.tenant,
                    name=raw_address,
                    defaults={
                        'code': f"MAIN-{company.id}"[:20],
                        'address': company.address_line1,
                        'city': company.city[:100],
                        'state': company.state[:100],
                        'country': company.country[:100],
                        'postal_code': company.postal_code[:20],
                        'phone': company.phone[:20]
                    }
                )
                print(f"Resolved to Warehouse ID: {hq.id} (Created: {created})")
                return hq.id
            return val

        # Create the order
        order = Order.objects.create(
            order_number=request.POST.get('order_number'),
            po_number=request.POST.get('po_number'),
            so_number=request.POST.get('so_number'),
            supplier_id=request.POST.get('supplier'),
            receiver_id=request.POST.get('receiver'),
            source_location_id=resolve_location(source_loc_val, request.user),
            destination_location_id=resolve_location(dest_loc_val, request.user),
            total_weight_target=request.POST.get('total_weight_target') or 0,
            shipping_terms_id=request.POST.get('shipping_terms'),
            representative_id=request.POST.get('representative'),
            status='confirmed', # Default to confirmed for manual entries
            payment_status='pending',
            created_by=request.user,
            tenant=request.user.tenant
        )
        
        # Handle Manifest Items
        materials = request.POST.getlist('material[]')
        weights = request.POST.getlist('weight[]')
        weight_units = request.POST.getlist('weight_unit[]')
        buy_prices = request.POST.getlist('buy_price[]')
        buy_price_units = request.POST.getlist('buy_price_unit[]')
        sell_prices = request.POST.getlist('sell_price[]')
        sell_price_units = request.POST.getlist('sell_price_unit[]')
        packagings = request.POST.getlist('packaging[]')
        
        for i in range(len(materials)):
            if materials[i]: # Only create if material name is provided
                ManifestItem.objects.create(
                    order=order,
                    material=materials[i],
                    weight=weights[i] or 0,
                    weight_unit=weight_units[i],
                    buy_price=buy_prices[i] or 0,
                    buy_price_unit=buy_price_units[i],
                    sell_price=sell_prices[i] or 0,
                    sell_price_unit=sell_price_units[i],
                    packaging=packagings[i] if i < len(packagings) else "",
                    is_palletized='is_palletized[]' in request.POST # Simplified for this pass
                )
        
        return redirect('orders:order_detail', pk=order.pk)
    
    logger.info(f'New order creation page accessed by {request.user}')
    
    user_company = request.user.company
    suppliers = Company.objects.filter(company_type='vendor')
    receivers = Company.objects.filter(company_type='customer')
    
    # Ensure current user's company is in both lists if it exists
    if user_company:
        suppliers = (suppliers | Company.objects.filter(pk=user_company.pk)).distinct()
        receivers = (receivers | Company.objects.filter(pk=user_company.pk)).distinct()
    
    inventory_items = InventoryItem.objects.filter(tenant=request.user.tenant) if request.user.tenant else InventoryItem.objects.all()
    if not inventory_items.exists():
        inventory_items = InventoryItem.plain_objects.all()

    # Show ONLY user's company warehouses
    if user_company:
        warehouses = Warehouse.plain_objects.filter(company=user_company).order_by('name')
    else:
        warehouses = Warehouse.plain_objects.all().order_by('name')

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
