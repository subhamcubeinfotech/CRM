from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from .models import Order, ManifestItem, Tag, ShippingTerm
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
        return context

@login_required
def order_update_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        status = request.POST.get('status')
        if status in dict(Order.STATUS_CHOICES):
            old_status = order.get_status_display()
            order.status = status
            order.save()
            logger.info(f'Order {order.order_number} status: {old_status} → {order.get_status_display()} by {request.user}')
    return redirect('orders:order_detail', pk=pk)

@login_required
def order_create(request):
    if request.method == 'POST':
        # Create the order
        order = Order.objects.create(
            order_number=request.POST.get('order_number'),
            po_number=request.POST.get('po_number'),
            so_number=request.POST.get('so_number'),
            supplier_id=request.POST.get('supplier'),
            receiver_id=request.POST.get('receiver'),
            source_location_id=request.POST.get('source_location'),
            destination_location_id=request.POST.get('destination_location'),
            total_weight_target=request.POST.get('total_weight_target') or 0,
            shipping_terms=request.POST.get('shipping_terms'),
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
    
    context = {
        'suppliers': suppliers,
        'receivers': receivers,
        'warehouses': Warehouse.objects.all(),
        'inventory_items': InventoryItem.objects.filter(tenant=request.user.tenant) if request.user.tenant else InventoryItem.objects.all(),
        'shipping_terms': ShippingTerm.objects.all(),
        'tags': Tag.objects.all(),
    }
    return render(request, 'orders/order_form.html', context)
