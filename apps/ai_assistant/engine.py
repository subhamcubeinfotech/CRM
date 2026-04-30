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
    
    return qs[:100]


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


def _smart_fallback(tenant, message):
    """Fallback logic that tries to be smart about what the user is asking"""
    msg = message.lower()
    from apps.shipments.models import Shipment
    from apps.orders.models import Order
    import re
    
    # 1. Look for Shipment Numbers (SHP-XXXX)
    ship_match = re.search(r'(SHP-\d{4}-\d+)', message, re.IGNORECASE)
    if ship_match:
        num = ship_match.group(1).upper()
        s = Shipment.objects.filter(tenant=tenant, shipment_number__icontains=num).first()
        if s:
            return f"🔍 **Shipment Found:**\n\n{format_shipment(s)}"

    # 2. Look for Order Numbers (STH-O-XXXX)
    order_match = re.search(r'(STH-O-[\d-]+)', message, re.IGNORECASE)
    if order_match:
        num = order_match.group(1).upper()
        o = Order.objects.filter(tenant=tenant, order_number__icontains=num).first()
        if o:
            return f"🔍 **Order Found:**\n\n{format_order(o)}"
            
    # 3. If no specific numbers, use the LLM to understand context
    return _conversational_fallback(tenant, message)


def _conversational_fallback(tenant, message):
    """Use the LLM for natural language processing"""
    # ... existing LLM logic ...
    pass


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
    (r'(?:show|find|lookup|get)\s+(?:only\s+|just\s+|me\s+)?(?:shipment|shp)[\s#-]*([\w\-\#]+)', 'shipment_lookup'),
    (r'(?:show|find|lookup|get)\s+(?:only\s+|just\s+|me\s+)?(SHP-[\w\-]+)', 'shipment_lookup'),  # Direct SHP-XXXX
    (r'\b(SHP-\d{4}-\d+)\b', 'shipment_lookup'),  # Any SHP number anywhere in message
    (r'(?:how many|count|total)\s+(?:shipments?)', 'shipment_count'),
    (r'(?:show\s+)?(?:all\s+)?(?:pending|waiting)\s+shipments?', 'shipment_status_filter'),
    (r'(?:in.transit|on.the.way)\s+shipments?', 'shipment_transit'),
    (r'(?:show\s+)?(?:all\s+)?(?:delivered)\s+shipments?', 'shipment_delivered'),
    (r'(?:overdue|late)\s+shipments?', 'shipment_overdue'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?shipments?\s+(?:for|of|from)\s+(.+)', 'shipment_by_company'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?shipments?', 'shipment_list'),
    (r'(?:recent|latest|last)\s+shipments?', 'shipment_recent'),
    
    # Inventory queries  
    (r'(?:show|list|get|find|what is the)\s+(?:inventory|stock)\s+(?:of|for|in)\s+(.+)', 'inventory_search'),
    (r'(?:inventory|stock)\s+(?:of|for|in)\s+(.+)', 'inventory_search'),
    (r'(?:low.stock|running.out|reorder)', 'inventory_low_stock'),
    (r'(?:how many|count|total)\s+(?:inventory|items?|products?)', 'inventory_count'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?inventory', 'inventory_list'),
    
    # Order queries
    (r'(?:show|find|lookup|get)\s+(?:only\s+|just\s+|me\s+)?(?:order|po)[\s#-]*([\w\-\#]+)', 'order_lookup'),
    (r'(?:show|find|lookup|get)\s+(?:only\s+|just\s+|me\s+)?(STH-O-[\w\-]+)', 'order_lookup'), # Direct STH-O-XXXX
    (r'\b(STH-O-\d{2}-\d+-\d+)\b', 'order_lookup'), # Any STH number anywhere
    (r'^(?:show\s+)?(?:all\s+)?open\s+orders?$', 'order_open'),
    (r'^(?:show\s+)?(?:all\s+)?(?:complete|delivered|closed)\s+orders?$', 'order_complete'),
    (r'^(?:show|list|get|find)\s+(?:all\s+)?orders?$', 'order_list'),
    (r'(?:how many|count|total)\s+(?:orders?)', 'order_count'),
    (r'(?:show|list|get|find)\s+(?:all\s+)?(?:\d+\s+)?orders?\s+(?:for|of|from)\s+(.+)', 'order_by_company'),
    (r'(?:show|list|get|find)\s+orders?', 'order_list'),
    
    # Company queries
    (r'(?:who|which|find|show)\s+(?:are\s+)?(?:the\s+)?(?:suppliers?|vendors?|all\s+vendors?)', 'company_vendors'),
    (r'(?:who|which|find|show)\s+(?:are\s+)?(?:the\s+)?(?:customers?|buyers?|all\s+customers?)', 'company_customers'),
    (r'(?:who|which|find|show)\s+(?:are\s+)?(?:the\s+)?carriers?', 'company_carriers'),
    (r'(?:show|list|find|get)\s+(?:all\s+)?companies', 'company_list'),
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
    status_display = o.get_status_display()
    if o.status in ['draft', 'confirmed', 'in_transit']:
        status_display = "Open"
    elif o.status in ['delivered', 'closed']:
        status_display = "Complete"
        
    return (
        f"**{o.order_number}** — {status_display}\n"
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
    Uses Rule-based first for speed, then Kimi LLM for intelligence.
    """
    tenant = user.tenant
    intent, entities = parse_intent(message)
    
    # ── Greetings ──
    if intent == 'greeting':
        return (
            f"👋 Hello {user.first_name or user.username}! I'm your FreightPro AI Assistant.\n\n"
            "I can help you with anything related to your shipments, orders, and inventory. Just ask me naturally! 🚀"
        )
    
    if intent == 'help':
        return (
            "Here are some things you can ask the assistant:\n\n"
            "• **Show pending shipments**\n"
            "• **Show open orders**\n"
            "• **Show low stock items**\n"
            "• **Dashboard stats**\n"
            "• **Get help**\n\n"
            "📦 **Shipments:**\n"
            "• \"Status of shipment SHP-2026-00001\"\n"
            "• \"Show all shipments\"\n"
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
        from apps.shipments.models import Shipment
        all_pending = Shipment.objects.filter(tenant=tenant, status='pending')
        total = all_pending.count()
        if total > 0:
            show = all_pending[:50]
            result = f"⏳ **{total} Pending Shipments (Showing {show.count()}):**\n\n"
            result += "\n\n".join(format_shipment(s) for s in show)
            if total > 50:
                result += f"\n\n📌 *...and {total - 50} more. Ask for a specific customer or date to filter.*"
            return result
        return "✅ No pending shipments right now!"
    
    if intent == 'shipment_transit':
        from apps.shipments.models import Shipment
        all_transit = Shipment.objects.filter(tenant=tenant, status='in_transit')
        total = all_transit.count()
        if total > 0:
            show = all_transit[:50]
            result = f"🚚 **{total} Shipments In Transit (Showing {show.count()}):**\n\n"
            result += "\n\n".join(format_shipment(s) for s in show)
            if total > 50:
                result += f"\n\n📌 *...and {total - 50} more.*"
            return result
        return "📭 No shipments currently in transit."
    
    if intent == 'shipment_delivered':
        from apps.shipments.models import Shipment
        all_delivered = Shipment.objects.filter(tenant=tenant, status='delivered')
        total = all_delivered.count()
        if total > 0:
            show = all_delivered[:50]
            result = f"✅ **{total} Delivered Shipments (Showing {show.count()}):**\n\n"
            result += "\n\n".join(format_shipment(s) for s in show)
            if total > 50:
                result += f"\n\n📌 *...and {total - 50} more.*"
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
        from apps.shipments.models import Shipment
        from django.db.models import Count
        all_shipments = Shipment.objects.filter(tenant=tenant)
        total = all_shipments.count()
        
        if total == 0:
            return "📭 No shipments found in the system."
        
        # Count by each status
        pending_count     = all_shipments.filter(status='pending').count()
        dispatched_count  = all_shipments.filter(status='dispatched').count()
        transit_count     = all_shipments.filter(status='in_transit').count()
        delivered_count   = all_shipments.filter(status='delivered').count()
        approved_count    = all_shipments.filter(status='approved').count()
        invoiced_count    = all_shipments.filter(status='invoiced').count()
        paid_count        = all_shipments.filter(status='paid').count()
        rejected_count    = all_shipments.filter(status='rejected').count()
        
        result = f"📦 **Hamare paas total {total} shipments hain:**\n\n"
        if pending_count:    result += f"  ⏳ Pending: **{pending_count}**\n"
        if dispatched_count: result += f"  🚀 Dispatched: **{dispatched_count}**\n"
        if transit_count:    result += f"  🚚 In Transit: **{transit_count}**\n"
        if delivered_count:  result += f"  ✅ Delivered: **{delivered_count}**\n"
        if approved_count:   result += f"  👍 Approved: **{approved_count}**\n"
        if invoiced_count:   result += f"  🧾 Invoiced: **{invoiced_count}**\n"
        if paid_count:       result += f"  💰 Paid: **{paid_count}**\n"
        if rejected_count:   result += f"  ❌ Rejected: **{rejected_count}**\n"
        
        result += "\n💬 **Konsi dikhani hai?** Batao jaise:\n"
        result += "  • *'show pending shipments'*\n"
        result += "  • *'show delivered shipments'*\n"
        result += "  • *'show shipment SHP-XXXX'* (ek specific)"
        return result
    
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
        orders = Order.objects.filter(tenant=tenant, status__in=['draft', 'confirmed', 'in_transit'])
        if orders.exists():
            result = f"🟢 **{orders.count()} Open Orders:**\n\n"
            result += "\n\n".join(format_order(o) for o in orders[:100])
            return result
        return "✅ No open orders right now."

    if intent == 'order_complete':
        from apps.orders.models import Order
        orders = Order.objects.filter(tenant=tenant, status__in=['delivered', 'closed'])
        if orders.exists():
            result = f"✅ **{orders.count()} Complete Orders:**\n\n"
            result += "\n\n".join(format_order(o) for o in orders[:100])
            return result
        return "📭 No complete orders found."

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
        from apps.orders.models import Order
        all_orders = Order.objects.filter(tenant=tenant)
        total = all_orders.count()
        
        if total == 0:
            return "📭 No orders found in the system."
        
        # Group statuses like the UI (Open vs Complete)
        # Open = Draft, Confirmed, In Transit
        open_count = all_orders.filter(status__in=['draft', 'confirmed', 'in_transit']).count()
        # Complete = Delivered, Closed
        complete_count = all_orders.filter(status__in=['delivered', 'closed']).count()
        
        result = f"📋 **Hamare paas total {total} orders hain:**\n\n"
        if open_count:     result += f"  🟢 Open Orders: **{open_count}**\n"
        if complete_count: result += f"  ✅ Complete Orders: **{complete_count}**\n"
        
        result += "\n💬 **Aapko kaunse dekhne hain?** Batao jaise:\n"
        result += "  • *'show open orders'*\n"
        result += "  • *'show complete orders'*\n"
        result += "  • *'order ORD-XXXX'* (ek specific)"
        return result
    
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
        
        # Extract potential IDs or keywords
        potential_ids = re.findall(r'[\w\-\#]+', message)
        search_terms = [t for t in potential_ids if (any(c.isdigit() for c in t) or '-' in t or len(t) > 2)]
        
        # Build search query
        query_filter = Q()
        if search_terms:
            for term in search_terms:
                query_filter |= Q(shipment_number__icontains=term) | Q(tracking_number__icontains=term)
        
        # Search Shipments
        ship_filter = query_filter | Q(customer__name__icontains=message) | Q(origin_city__icontains=message)
        if "shipment" in message.lower() or "shp" in message.lower():
            # If they just said "shipments", show recent ones
            ship_matches = Shipment.objects.filter(tenant=user.tenant).order_by('-created_at')[:10]
        else:
            ship_matches = Shipment.objects.filter(tenant=user.tenant).filter(ship_filter).select_related('order', 'customer').distinct()[:10]
            
        if ship_matches:
            live_context += "\nSHIPMENTS:\n" + "\n".join(f"- {s.shipment_number}: {s.get_status_display()} | Customer: {s.customer.name} | Route: {s.origin_full} -> {s.destination_full} | Date: {s.pickup_date}" for s in ship_matches)
        
        # Search Orders
        order_filter = Q(order_number__icontains=message) | Q(po_number__icontains=message) | Q(supplier__name__icontains=message)
        if "order" in message.lower() or "po" in message.lower():
            # If they just said "orders", show recent ones
            order_matches = Order.objects.filter(tenant=user.tenant).order_by('-created_at')[:10]
        else:
            order_matches = Order.objects.filter(tenant=user.tenant).filter(order_filter).distinct()[:10]
            
        if order_matches:
            live_context += "\nORDERS:\n" + "\n".join(f"- {o.order_number}: {o.get_status_display()} | Supplier: {o.supplier.name} | Receiver: {o.receiver.name} | Date: {o.order_date}" for o in order_matches)
            
        # Search Inventory
        inv_filter = Q(product_name__icontains=message) | Q(sku__icontains=message) | Q(warehouse__city__icontains=message)
        if "inventory" in message.lower() or "stock" in message.lower() or "item" in message.lower():
            inv_matches = InventoryItem.objects.filter(tenant=user.tenant).order_by('-quantity')[:10]
        else:
            inv_matches = InventoryItem.objects.filter(tenant=user.tenant).filter(inv_filter)[:10]
        if inv_matches:
            live_context += "\nINVENTORY:\n" + "\n".join(f"- {i.product_name} ({i.sku}): {i.quantity} {i.unit_of_measure} at {i.warehouse.city}" for i in inv_matches)

        # Search Companies
        company_matches = Company.objects.filter(tenant=user.tenant, is_active=True).filter(Q(name__icontains=message) | Q(city__icontains=message))[:10]
        if company_matches:
            live_context += "\nCOMPANIES/PARTNERS:\n" + "\n".join(f"- {c.name} ({c.get_company_type_display()}): Location: {c.city}, {c.state}" for c in company_matches)

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.moonshot.ai/v1",
        )
        
        system_prompt = f"""
        You are the 'FreightPro Oracle', a high-intelligence AI Logistics Expert and trusted business advisor for FreightPro CRM users.
        
        Your role is to provide accurate, helpful, and insightful responses about the user's logistics business data. You have access to live, real-time data from their CRM system including shipments, orders, inventory, companies, and financial metrics.
        
        DATA CONTEXT PROVIDED:
        ---
        SYSTEM OVERVIEW:
        - Total Shipments: {stats['total_shipments']} ({stats['pending_shipments']} Pending, {stats['in_transit_shipments']} In Transit, {stats['delivered_shipments']} Delivered)
        - Total Orders: {stats['total_orders']} ({stats['open_orders']} Open)
        - Inventory: {stats['total_inventory_items']} items ({stats['low_stock_items']} Low Stock)
        - Total Companies: {stats['total_companies']} ({stats['vendors']} Vendors, {stats['customers']} Customers, {stats['carriers']} Carriers)
        - Total Revenue: ${stats['total_revenue']:,.2f}
        
        SEARCH RESULTS FROM DATABASE:
        {live_context if live_context else "No specific records found for your keywords, use the System Overview for general answers."}
        ---
        
        RESPONSE GUIDELINES:
        1. **Be Professional Yet Friendly**: Use a conversational tone with appropriate emojis. Act as a knowledgeable colleague.
        2. **Accuracy First**: Only provide information from the data context. If something isn't in the provided data, say so clearly.
        3. **Actionable Insights**: When showing data, provide brief analysis or recommendations when relevant.
        4. **Context-Aware**: Reference the user's specific data (e.g., "Based on your current 5 pending shipments...").
        5. **Helpful Suggestions**: If they ask about operations, suggest related actions they might take in the system.
        6. **Structured Responses**: For lists or multiple items, use clear formatting with bullet points or numbered lists.
        7. **Greet Warmly**: Always respond to greetings with enthusiasm and personalization.
        8. **Handle Uncertainty**: If a query doesn't match available data, offer alternatives or ask for clarification.
        
        EXPERTISE AREAS:
        - Shipment tracking and status analysis
        - Order management and fulfillment
        - Inventory optimization and stock alerts
        - Company relationship management
        - Business performance metrics and insights
        - Operational efficiency recommendations
        
        Remember: You are their AI business partner - knowledgeable, reliable, and always focused on helping them succeed in logistics.
        """
        
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Kimi fallback failed for user {user.username}: {e}")
        return _static_fallback(message)


def _static_fallback(message):
    return (
        "🤔 I'm not sure what you're asking. Here are some quick actions:\n\n"
        "• Show pending shipments\n"
        "• Show open orders\n"
        "• Show low stock items\n"
        "• Dashboard stats\n"
        "• Help / Examples\n\n"
        "Just ask me anything about shipments, orders, inventory, or companies! 🚀"
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
