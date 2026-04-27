"""
AI Query Engine - Smart database querying for the chat assistant.
Works in two modes:
1. Rule-based: Keyword matching + Django ORM (no API key needed)
2. LLM-enhanced: Uses OpenAI API for better NLU (when key is available)
"""
import re
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger('apps.ai_assistant')


def search_shipments(tenant, **kwargs):
    """Search shipments with various filters"""
    from apps.shipments.models import Shipment
    qs = Shipment.objects.filter(tenant=tenant)
    
    if kwargs.get('shipment_number'):
        # Try exact match first for better precision
        exact_match = qs.filter(shipment_number__iexact=kwargs['shipment_number'])
        if exact_match.exists():
            return exact_match
        qs = qs.filter(shipment_number__icontains=kwargs['shipment_number'])
    if kwargs.get('status'):
        qs = qs.filter(status=kwargs['status'])
    if kwargs.get('customer_name'):
        qs = qs.filter(customer__name__icontains=kwargs['customer_name'])
    if kwargs.get('carrier_name'):
        qs = qs.filter(carrier__name__icontains=kwargs['carrier_name'])
    if kwargs.get('origin'):
        qs = qs.filter(Q(origin_city__icontains=kwargs['origin']) | Q(origin_state__icontains=kwargs['origin']))
    if kwargs.get('destination'):
        qs = qs.filter(Q(destination_city__icontains=kwargs['destination']) | Q(destination_state__icontains=kwargs['destination']))
    if kwargs.get('days'):
        cutoff = timezone.now() - timedelta(days=int(kwargs['days']))
        qs = qs.filter(created_at__gte=cutoff)
    
    return qs[:20]


def search_inventory(tenant, **kwargs):
    """Search inventory items"""
    from apps.inventory.models import InventoryItem
    qs = InventoryItem.objects.filter(tenant=tenant)
    
    if kwargs.get('product_name'):
        qs = qs.filter(product_name__icontains=kwargs['product_name'])
    if kwargs.get('sku'):
        qs = qs.filter(sku__icontains=kwargs['sku'])
    if kwargs.get('warehouse'):
        qs = qs.filter(Q(warehouse__name__icontains=kwargs['warehouse']) | Q(warehouse__city__icontains=kwargs['warehouse']))
    if kwargs.get('low_stock'):
        from django.db.models import F
        qs = qs.filter(quantity__lte=F('reorder_level'))
    if kwargs.get('company_name'):
        qs = qs.filter(company__name__icontains=kwargs['company_name'])
    
    return qs[:20]


def search_orders(tenant, **kwargs):
    """Search orders"""
    from apps.orders.models import Order
    qs = Order.objects.filter(tenant=tenant)
    
    if kwargs.get('order_number'):
        # Try exact match first for better precision
        exact_match = qs.filter(order_number__iexact=kwargs['order_number'])
        if exact_match.exists():
            return exact_match
        qs = qs.filter(order_number__icontains=kwargs['order_number'])
    if kwargs.get('status'):
        qs = qs.filter(status=kwargs['status'])
    if kwargs.get('supplier_name'):
        qs = qs.filter(supplier__name__icontains=kwargs['supplier_name'])
    if kwargs.get('receiver_name'):
        qs = qs.filter(receiver__name__icontains=kwargs['receiver_name'])
    if kwargs.get('po_number'):
        qs = qs.filter(po_number__icontains=kwargs['po_number'])
    
    return qs[:20]


def search_companies(tenant, **kwargs):
    """Search companies"""
    from apps.accounts.models import Company
    qs = Company.objects.filter(tenant=tenant, is_active=True)
    
    if kwargs.get('name'):
        qs = qs.filter(name__icontains=kwargs['name'])
    if kwargs.get('company_type'):
        qs = qs.filter(company_type=kwargs['company_type'])
    if kwargs.get('city'):
        qs = qs.filter(city__icontains=kwargs['city'])
    if kwargs.get('material'):
        qs = qs.filter(material_tags__name__icontains=kwargs['material']).distinct()
    
    return qs[:20]


def get_dashboard_stats(tenant):
    """Get summary stats for dashboard"""
    from apps.shipments.models import Shipment
    from apps.orders.models import Order
    from apps.inventory.models import InventoryItem
    from apps.accounts.models import Company
    
    shipments = Shipment.objects.filter(tenant=tenant)
    orders = Order.objects.filter(tenant=tenant)
    inventory = InventoryItem.objects.filter(tenant=tenant)
    companies = Company.objects.filter(tenant=tenant, is_active=True)
    
    return {
        'total_shipments': shipments.count(),
        'pending_shipments': shipments.filter(status='pending').count(),
        'in_transit_shipments': shipments.filter(status='in_transit').count(),
        'delivered_shipments': shipments.filter(status='delivered').count(),
        'total_orders': orders.count(),
        'open_orders': orders.exclude(status__in=['closed', 'cancelled']).count(),
        'total_inventory_items': inventory.count(),
        'low_stock_items': inventory.filter(quantity__lte=10).count(),
        'total_companies': companies.count(),
        'vendors': companies.filter(company_type='vendor').count(),
        'customers': companies.filter(company_type='customer').count(),
        'carriers': companies.filter(company_type='carrier').count(),
        'total_revenue': float(shipments.aggregate(s=Sum('revenue'))['s'] or 0),
    }


# ─── Rule-Based Query Parser ───────────────────────────────────────────────

INTENT_PATTERNS = [
    # Shipment queries
    (r'(?:status|track|where)\s+(?:of\s+)?(?:shipment|shp)[\s#-]*([\w\-\#]+)', 'shipment_lookup'),
    (r'(?:how many|count|total)\s+(?:shipments?)', 'shipment_count'),
    (r'(?:pending|waiting)\s+shipments?', 'shipment_status_filter'),
    (r'(?:in.transit|on.the.way)\s+shipments?', 'shipment_transit'),
    (r'(?:delivered)\s+shipments?', 'shipment_delivered'),
    (r'(?:overdue|late)\s+shipments?', 'shipment_overdue'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?shipments?\s+(?:for|of|from)\s+(.+)', 'shipment_by_company'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?shipments?', 'shipment_list'),
    (r'(?:recent|latest|last)\s+shipments?', 'shipment_recent'),
    
    # Inventory queries  
    (r'(?:inventory|stock)\s+(?:of|for|in)\s+(.+)', 'inventory_search'),
    (r'(?:low.stock|running.out|reorder)', 'inventory_low_stock'),
    (r'(?:how many|count|total)\s+(?:inventory|items?|products?)', 'inventory_count'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?inventory', 'inventory_list'),
    
    # Order queries
    (r'(?:order|po)[\s#-]*([\w\-\#]+)', 'order_lookup'),
    (r'(?:how many|count|total)\s+(?:orders?)', 'order_count'),
    (r'(?:open|active|pending)\s+orders?', 'order_open'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?orders?\s+(?:for|of|from)\s+(.+)', 'order_by_company'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?orders?', 'order_list'),
    
    # Company queries
    (r'(?:who|which)\s+(?:are\s+)?(?:the\s+)?(?:suppliers?|vendors?)', 'company_vendors'),
    (r'(?:who|which)\s+(?:are\s+)?(?:the\s+)?(?:customers?|buyers?)', 'company_customers'),
    (r'(?:who|which)\s+(?:are\s+)?(?:the\s+)?carriers?', 'company_carriers'),
    (r'(?:show|list|find)\s+(?:all\s+)?companies', 'company_list'),
    (r'(?:company|supplier|vendor|customer|carrier)\s+(.+)', 'company_search'),
    
    # Dashboard / stats
    (r'(?:dashboard|summary|overview|stats|statistics|report)', 'dashboard_stats'),
    (r'(?:how.is|what.is)\s+(?:the\s+)?(?:business|performance)', 'dashboard_stats'),
    
    # Numbered shortcuts
    (r'^1$', 'shipment_status_filter'),
    (r'^2$', 'order_open'),
    (r'^3$', 'inventory_low_stock'),
    (r'^4$', 'dashboard_stats'),
    (r'^5$', 'help'),

    # Greetings
    (r'^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|namaste|hola)', 'greeting'),
    (r'^(?:help|what can you do|commands)', 'help'),
]


def parse_intent(message):
    """Parse user message to determine intent and extract entities"""
    msg = message.lower().strip()
    
    for pattern, intent in INTENT_PATTERNS:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            return intent, match.groups()
    
    return 'unknown', ()


def format_shipment(s):
    """Format a shipment for display"""
    return (
        f"**{s.shipment_number}** — {s.get_status_display()}\n"
        f"  Customer: {s.customer.name}\n"
        f"  Route: {s.origin_full} → {s.destination_full}\n"
        f"  Weight: {s.total_weight} kg | Revenue: ${s.revenue}"
    )


def format_order(o):
    """Format an order for display"""
    return (
        f"**{o.order_number}** — {o.get_status_display()}\n"
        f"  Supplier: {o.supplier.name} → Receiver: {o.receiver.name}\n"
        f"  Target: {o.total_weight_target} {o.total_weight_unit} | PO: {o.po_number or 'N/A'}"
    )


def format_inventory(item):
    """Format an inventory item for display"""
    return (
        f"**{item.sku}** — {item.product_name}\n"
        f"  Warehouse: {item.warehouse.city}\n"
        f"  Stock: {item.quantity} {item.unit_of_measure} | Price: ${item.unit_cost}/{item.price_unit}"
    )


def format_company(c):
    """Format a company for display"""
    return f"**{c.name}** ({c.get_company_type_display()}) — {c.city}, {c.state}"


def process_query(user, message):
    """
    Main entry point: process a user's natural language query.
    Returns a response string.
    """
    tenant = user.tenant
    intent, entities = parse_intent(message)
    
    # ── Greetings ──
    if intent == 'greeting':
        return (
            f"👋 Hello {user.first_name or user.username}! I'm your FreightPro AI Assistant.\n\n"
            "I can help you with:\n"
            "• **Shipments** — track, search, count\n"
            "• **Orders** — lookup, status, filter\n"
            "• **Inventory** — stock levels, low stock alerts\n"
            "• **Companies** — find vendors, customers, carriers\n"
            "• **Dashboard stats** — business overview\n\n"
            "Just ask me anything! 🚀"
        )
    
    if intent == 'help':
        return (
            "Here are some things you can ask (Type the **Number** or the command):\n\n"
            "1️⃣ **Show pending shipments** (Type **1**)\n"
            "2️⃣ **Show open orders** (Type **2**)\n"
            "3️⃣ **Show low stock items** (Type **3**)\n"
            "4️⃣ **Dashboard stats** (Type **4**)\n"
            "5️⃣ **Get help** (Type **5**)\n\n"
            "📦 **Shipments:**\n"
            "• \"Status of shipment SHP-2026-00001\"\n"
            "• \"How many shipments are in transit?\"\n\n"
            "📋 **Orders:**\n"
            "• \"Order ORD-2026-00001\"\n\n"
            "📊 **Inventory:**\n"
            "• \"Inventory in warehouse X\"\n\n"
            "🏢 **Companies:**\n"
            "• \"Find company ABC\""
        )
    
    # ── Shipment queries ──
    if intent == 'shipment_lookup':
        num = entities[0] if entities else ''
        shipments = search_shipments(tenant, shipment_number=num)
        if shipments.exists():
            return "🔍 **Shipment Found:**\n\n" + "\n\n".join(format_shipment(s) for s in shipments)
        return f"❌ No shipment found matching '{num}'."
    
    if intent == 'shipment_count':
        from apps.shipments.models import Shipment
        count = Shipment.objects.filter(tenant=tenant).count()
        return f"📦 You have **{count}** total shipments in the system."
    
    if intent == 'shipment_status_filter':
        shipments = search_shipments(tenant, status='pending')
        if shipments.exists():
            result = f"⏳ **{shipments.count()} Pending Shipments:**\n\n"
            result += "\n\n".join(format_shipment(s) for s in shipments[:10])
            return result
        return "✅ No pending shipments right now!"
    
    if intent == 'shipment_transit':
        shipments = search_shipments(tenant, status='in_transit')
        if shipments.exists():
            result = f"🚚 **{shipments.count()} Shipments In Transit:**\n\n"
            result += "\n\n".join(format_shipment(s) for s in shipments[:10])
            return result
        return "📭 No shipments currently in transit."
    
    if intent == 'shipment_delivered':
        shipments = search_shipments(tenant, status='delivered')
        if shipments.exists():
            result = f"✅ **{shipments.count()} Delivered Shipments:**\n\n"
            result += "\n\n".join(format_shipment(s) for s in shipments[:10])
            return result
        return "📭 No delivered shipments found."
    
    if intent == 'shipment_overdue':
        from apps.shipments.models import Shipment
        overdue = Shipment.objects.filter(
            tenant=tenant,
            estimated_delivery_date__lt=timezone.now().date()
        ).exclude(status__in=['delivered', 'paid'])
        if overdue.exists():
            result = f"⚠️ **{overdue.count()} Overdue Shipments:**\n\n"
            result += "\n\n".join(format_shipment(s) for s in overdue[:10])
            return result
        return "✅ No overdue shipments. Everything is on schedule!"
    
    if intent == 'shipment_by_company':
        name = entities[0].strip() if entities else ''
        shipments = search_shipments(tenant, customer_name=name)
        if not shipments.exists():
            shipments = search_shipments(tenant, carrier_name=name)
        if shipments.exists():
            result = f"📦 **Shipments for '{name}':**\n\n"
            result += "\n\n".join(format_shipment(s) for s in shipments[:10])
            return result
        return f"❌ No shipments found for '{name}'."
    
    if intent == 'shipment_list':
        shipments = search_shipments(tenant)
        if shipments.exists():
            result = f"📦 **Recent Shipments ({shipments.count()}):**\n\n"
            result += "\n\n".join(format_shipment(s) for s in shipments[:10])
            return result
        return "📭 No shipments found."
    
    if intent == 'shipment_recent':
        shipments = search_shipments(tenant, days=7)
        if shipments.exists():
            result = f"📦 **Shipments from last 7 days ({shipments.count()}):**\n\n"
            result += "\n\n".join(format_shipment(s) for s in shipments[:10])
            return result
        return "📭 No shipments in the last 7 days."
    
    # ── Inventory queries ──
    if intent == 'inventory_search':
        term = entities[0].strip() if entities else ''
        items = search_inventory(tenant, product_name=term)
        if not items.exists():
            items = search_inventory(tenant, warehouse=term)
        if items.exists():
            result = f"📊 **Inventory matching '{term}' ({items.count()}):**\n\n"
            result += "\n\n".join(format_inventory(i) for i in items[:10])
            return result
        return f"❌ No inventory found matching '{term}'."
    
    if intent == 'inventory_low_stock':
        from apps.inventory.models import InventoryItem
        low = InventoryItem.objects.filter(tenant=tenant, quantity__lte=10)
        if low.exists():
            result = f"⚠️ **{low.count()} Low Stock Items:**\n\n"
            result += "\n\n".join(format_inventory(i) for i in low[:10])
            return result
        return "✅ All inventory levels are healthy!"
    
    if intent == 'inventory_count':
        from apps.inventory.models import InventoryItem
        count = InventoryItem.objects.filter(tenant=tenant).count()
        return f"📊 You have **{count}** inventory items in the system."
    
    if intent == 'inventory_list':
        items = search_inventory(tenant)
        if items.exists():
            result = f"📊 **Inventory Items ({items.count()}):**\n\n"
            result += "\n\n".join(format_inventory(i) for i in items[:10])
            return result
        return "📭 No inventory items found."
    
    # ── Order queries ──
    if intent == 'order_lookup':
        num = entities[0] if entities else ''
        orders = search_orders(tenant, order_number=num)
        if not orders.exists():
            orders = search_orders(tenant, po_number=num)
        if orders.exists():
            return "🔍 **Order Found:**\n\n" + "\n\n".join(format_order(o) for o in orders)
        return f"❌ No order found matching '{num}'."
    
    if intent == 'order_count':
        from apps.orders.models import Order
        count = Order.objects.filter(tenant=tenant).count()
        return f"📋 You have **{count}** orders in the system."
    
    if intent == 'order_open':
        from apps.orders.models import Order
        open_orders = Order.objects.filter(tenant=tenant).exclude(status__in=['delivered', 'closed', 'cancelled'])
        if open_orders.exists():
            result = f"📋 **{open_orders.count()} Open Orders:**\n\n"
            result += "\n\n".join(format_order(o) for o in open_orders[:10])
            return result
        return "✅ No open orders right now."
    
    if intent == 'order_by_company':
        name = entities[0].strip() if entities else ''
        orders = search_orders(tenant, supplier_name=name)
        if not orders.exists():
            orders = search_orders(tenant, receiver_name=name)
        if orders.exists():
            result = f"📋 **Orders for '{name}':**\n\n"
            result += "\n\n".join(format_order(o) for o in orders[:10])
            return result
        return f"❌ No orders found for '{name}'."
    
    if intent == 'order_list':
        orders = search_orders(tenant)
        if orders.exists():
            result = f"📋 **Recent Orders ({orders.count()}):**\n\n"
            result += "\n\n".join(format_order(o) for o in orders[:10])
            return result
        return "📭 No orders found."
    
    # ── Company queries ──
    if intent == 'company_vendors':
        companies = search_companies(tenant, company_type='vendor')
        if companies.exists():
            result = f"🏭 **Vendors ({companies.count()}):**\n\n"
            result += "\n".join(format_company(c) for c in companies[:15])
            return result
        return "❌ No vendors found."
    
    if intent == 'company_customers':
        companies = search_companies(tenant, company_type='customer')
        if companies.exists():
            result = f"👥 **Customers ({companies.count()}):**\n\n"
            result += "\n".join(format_company(c) for c in companies[:15])
            return result
        return "❌ No customers found."
    
    if intent == 'company_carriers':
        companies = search_companies(tenant, company_type='carrier')
        if companies.exists():
            result = f"🚛 **Carriers ({companies.count()}):**\n\n"
            result += "\n".join(format_company(c) for c in companies[:15])
            return result
        return "❌ No carriers found."
    
    if intent == 'company_list':
        companies = search_companies(tenant)
        if companies.exists():
            result = f"🏢 **Companies ({companies.count()}):**\n\n"
            result += "\n".join(format_company(c) for c in companies[:15])
            return result
        return "❌ No companies found."
    
    if intent == 'company_search':
        name = entities[0].strip() if entities else ''
        companies = search_companies(tenant, name=name)
        if companies.exists():
            result = f"🔍 **Companies matching '{name}':**\n\n"
            result += "\n".join(format_company(c) for c in companies[:15])
            return result
        return f"❌ No companies found matching '{name}'."
    
    # ── Dashboard ──
    if intent == 'dashboard_stats':
        stats = get_dashboard_stats(tenant)
        return (
            "📊 **Business Dashboard**\n\n"
            f"**Shipments:** {stats['total_shipments']} total\n"
            f"  • ⏳ Pending: {stats['pending_shipments']}\n"
            f"  • 🚚 In Transit: {stats['in_transit_shipments']}\n"
            f"  • ✅ Delivered: {stats['delivered_shipments']}\n\n"
            f"**Orders:** {stats['total_orders']} total ({stats['open_orders']} open)\n\n"
            f"**Inventory:** {stats['total_inventory_items']} items ({stats['low_stock_items']} low stock)\n\n"
            f"**Companies:** {stats['total_companies']} total\n"
            f"  • 🏭 Vendors: {stats['vendors']}\n"
            f"  • 👥 Customers: {stats['customers']}\n"
            f"  • 🚛 Carriers: {stats['carriers']}\n\n"
            f"**Total Revenue:** ${stats['total_revenue']:,.2f}"
        )
    
    # ── Unknown intent: Try smart fallback ──
    result = _smart_fallback(tenant, message)
    if result:
        return result
        
    return _conversational_fallback(user, message)


def search_invoices(tenant, **kwargs):
    """Search invoices"""
    from apps.invoicing.models import Invoice
    qs = Invoice.objects.filter(tenant=tenant)
    
    if kwargs.get('invoice_number'):
        qs = qs.filter(invoice_number__icontains=kwargs['invoice_number'])
    if kwargs.get('status'):
        qs = qs.filter(status=kwargs['status'])
    if kwargs.get('customer_name'):
        qs = qs.filter(customer__name__icontains=kwargs['customer_name'])
        
    return qs[:10]


def search_contacts(tenant, **kwargs):
    """Search users/contacts"""
    from apps.accounts.models import CustomUser
    qs = CustomUser.objects.filter(tenant=tenant, is_active=True)
    
    if kwargs.get('name'):
        qs = qs.filter(Q(first_name__icontains=kwargs['name']) | Q(last_name__icontains=kwargs['name']) | Q(username__icontains=kwargs['name']))
    if kwargs.get('role'):
        qs = qs.filter(role=kwargs['role'])
        
    return qs[:10]


def _conversational_fallback(user, message):
    """Use Kimi (Moonshot AI) to provide a smart conversational response grounded in LIVE CRM data."""
    api_key = getattr(settings, 'KIMI_API_KEY', '').strip()
    if not api_key:
        return _static_fallback(message)

    try:
        # 1. Gather Context (Dashboard Stats)
        stats = get_dashboard_stats(user.tenant)
        
        # 2. Gather LIVE Data (Broad Search across all models)
        live_context = ""
        from apps.shipments.models import Shipment
        from apps.orders.models import Order
        from apps.inventory.models import InventoryItem
        from apps.accounts.models import Company, CustomUser
        from apps.invoicing.models import Invoice
        
        # Extract potential IDs or keywords (words with hyphens, numbers, or length > 3)
        potential_ids = re.findall(r'[\w\-\#]+', message)
        # Filter for things that look like IDs (have numbers or hyphens) or are significant words
        search_terms = [t for t in potential_ids if (any(c.isdigit() for c in t) or '-' in t or len(t) > 3)]
        
        # If we have specific terms, search them. Otherwise use whole message for broad lookup.
        query_filter = Q()
        if search_terms:
            for term in search_terms:
                query_filter |= Q(shipment_number__icontains=term) | Q(tracking_number__icontains=term) | Q(order__order_number__icontains=term) | Q(order__po_number__icontains=term)
        else:
            query_filter = Q(shipment_number__icontains=message) | Q(customer__name__icontains=message)

        # Search Shipments
        ship_matches = Shipment.objects.filter(tenant=user.tenant).filter(query_filter).select_related('order', 'customer').distinct()[:5]
        if ship_matches:
            live_context += "\nRelevant Shipments:\n" + "\n".join(f"- {s.shipment_number}: {s.get_status_display()} (Linked Order: {s.order.order_number if s.order else 'N/A'}, Customer: {s.customer.name})" for s in ship_matches)
        
        # Search Orders
        order_filter = Q()
        if search_terms:
            for term in search_terms:
                order_filter |= Q(order_number__icontains=term) | Q(po_number__icontains=term) | Q(supplier__name__icontains=term)
        else:
            order_filter = Q(order_number__icontains=message)
            
        order_matches = Order.objects.filter(tenant=user.tenant).filter(order_filter).distinct()[:5]
        if order_matches:
            live_context += "\nRelevant Orders:\n" + "\n".join(f"- {o.order_number}: {o.get_status_display()} (Supplier: {o.supplier.name})" for o in order_matches)
            
        # Search Inventory
        inv_matches = InventoryItem.objects.filter(tenant=user.tenant).filter(
            Q(product_name__icontains=message) | Q(sku__icontains=message)
        )[:5]
        if inv_matches:
            live_context += "\nRelevant Inventory:\n" + "\n".join(f"- {i.product_name} ({i.sku}): {i.quantity} {i.unit_of_measure} at {i.warehouse.name}" for i in inv_matches)

        # Search Invoices
        inv_bill_matches = Invoice.objects.filter(tenant=user.tenant).filter(
            Q(invoice_number__icontains=message) | Q(customer__name__icontains=message)
        )[:5]
        if inv_bill_matches:
            live_context += "\nRelevant Invoices:\n" + "\n".join(f"- {i.invoice_number}: {i.get_status_display()} (Total: ${i.total}, Due: {i.due_date})" for i in inv_bill_matches)
            
        # Search Contacts/Team
        contact_matches = CustomUser.objects.filter(tenant=user.tenant, is_active=True).filter(
            Q(first_name__icontains=message) | Q(last_name__icontains=message) | Q(email__icontains=message)
        )[:5]
        if contact_matches:
            live_context += "\nRelevant Team/Contacts:\n" + "\n".join(f"- {u.get_full_name() or u.username}: {u.role} (Email: {u.email})" for u in contact_matches)

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.moonshot.ai/v1",
        )
        
        system_prompt = f"""
        You are the FreightPro AI Logistics Assistant. You help users manage their CRM data.
        You have direct access to the database results provided below.
        
        STRICT GROUNDING RULES:
        1. Answer based on the 'LIVE CRM DATA' and 'System Stats' provided.
        2. PRECISION IS KEY: If the user asks for a SPECIFIC record, provide details for ONLY THAT ONE record.
        3. HANDLING LISTS: If the user asks to "show all" or for a list, and you have multiple matches in 'LIVE CRM DATA', explain that you are showing the MOST RELEVANT/RECENT ones (e.g., "Here are the top 5 matches out of {stats['total_orders']} total orders"). 
        4. NEVER claim to be showing the full list if you only see a few records in 'LIVE CRM DATA'.
        5. Use a helpful, professional tone. If the user asks for more than what you can see, suggest they visit the specific dashboard section.
        6. If no specific records are found, use the 'System Stats' to give a general overview.
        
        SYSTEM STATS:
        - Shipments: {stats['total_shipments']} ({stats['pending_shipments']} pending, {stats['in_transit_shipments']} in transit, {stats['delivered_shipments']} delivered)
        - Orders: {stats['total_orders']} ({stats['open_orders']} open)
        - Inventory: {stats['total_inventory_items']} items ({stats['low_stock_items']} low stock)
        - Companies: {stats['total_companies']} ({stats['vendors']} vendors, {stats['customers']} customers)
        
        LIVE CRM DATA SEARCH RESULTS:
        {live_context if live_context else "No specific matching records found for the keywords in the query."}
        """
        
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.2,
            max_tokens=800,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Kimi fallback failed for user {user.username}: {e}")
        return _static_fallback(message)


def _static_fallback(message):
    return (
        "🤔 I'm not sure what you're asking. Here are some quick actions:\n\n"
        "1️⃣ **1** — Show pending shipments\n"
        "2️⃣ **2** — Show open orders\n"
        "3️⃣ **3** — Show low stock items\n"
        "4️⃣ **4** — Dashboard stats\n"
        "5️⃣ **5** — Help / Examples\n\n"
        "Just type the **number** or ask me anything! 🚀"
    )


def _smart_fallback(tenant, message):
    """Try to find something relevant when intent is unclear (Legacy/Fast check)"""
    msg = message.lower().strip()
    
    # Try as shipment number
    from apps.shipments.models import Shipment
    shipment = Shipment.objects.filter(tenant=tenant, shipment_number__icontains=msg).first()
    if shipment:
        return "🔍 **Found Shipment:**\n\n" + format_shipment(shipment)
    
    # Try as order number
    from apps.orders.models import Order
    order = Order.objects.filter(tenant=tenant, order_number__icontains=msg).first()
    if order:
        return "🔍 **Found Order:**\n\n" + format_order(order)
    
    return None # Let the caller handle conversational fallback
