"""
AI Assistant Views - Chat API and Pending Inventory management
"""
import json
import logging
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import ChatSession, ChatMessage, PendingInventoryEmail, PendingInventoryItem, BuyerRequirement, SmartMatch
from .engine import process_query

logger = logging.getLogger('apps.ai_assistant')


# ─── FEATURE A: Chat API ────────────────────────────────────────────────────

@login_required
@require_POST
def chat_api(request):
    """AJAX endpoint for chat messages"""
    try:
        body = json.loads(request.body)
        message = body.get('message', '').strip()
    except (json.JSONDecodeError, AttributeError):
        message = request.POST.get('message', '').strip()
    
    if not message:
        return JsonResponse({'error': 'Empty message'}, status=400)
    
    # Get or create active session
    session, _ = ChatSession.objects.get_or_create(
        user=request.user,
        tenant=request.user.tenant,
        is_active=True,
        defaults={'title': message[:50]}
    )
    
    # Save user message
    ChatMessage.objects.create(session=session, role='user', content=message)
    
    # Process query
    try:
        response_text = process_query(request.user, message)
    except Exception as e:
        logger.error('AI Engine error: %s', str(e))
        response_text = "⚠️ Sorry, I encountered an error processing your request. Please try again."
    
    # Save assistant response
    ChatMessage.objects.create(session=session, role='assistant', content=response_text)
    
    # Update session title if it's the first message
    if session.messages.filter(role='user').count() == 1:
        session.title = message[:80]
        session.save(update_fields=['title', 'updated_at'])
    
    return JsonResponse({
        'response': response_text,
        'session_id': session.id,
    })


@login_required
@require_GET
def chat_history(request):
    """Get recent chat history"""
    session = ChatSession.objects.filter(user=request.user, tenant=request.user.tenant, is_active=True).first()
    if not session:
        return JsonResponse({'messages': []})
    
    messages = session.messages.order_by('-created_at')[:30]
    data = [{
        'role': m.role,
        'content': m.content,
        'time': m.created_at.strftime('%I:%M %p'),
    } for m in reversed(messages)]
    
    return JsonResponse({'messages': data})


@login_required
def chat_clear(request):
    """Clear chat history — starts a new session"""
    if request.method == 'POST':
        ChatSession.objects.filter(user=request.user, tenant=request.user.tenant, is_active=True).update(is_active=False)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'POST only'}, status=405)


# ─── FEATURE B: Pending Inventory ────────────────────────────────────────────

@login_required
def pending_inventory_list(request):
    """Show all pending inventory emails for review"""
    # Trigger fetch on page load so it feels automatic
    from .email_ingestion import fetch_and_process_emails
    try:
        fetch_and_process_emails(request.user.tenant, max_emails=5, request_user=request.user)
    except Exception as e:
        logger.error(f"Automatic fetch failed: {e}")

    # Visibility Filter: Users see their own emails. Admins see everything.
    from django.db.models import Q
    visibility_filter = Q(tenant=request.user.tenant)
    if not getattr(request.user, 'is_admin', False):
        visibility_filter &= Q(fetched_by=request.user)

    emails = PendingInventoryEmail.objects.filter(
        visibility_filter,
        status='pending'
    ).prefetch_related('items')
    
    # Also get recently processed
    recent = PendingInventoryEmail.objects.filter(
        visibility_filter
    ).exclude(status='pending').order_by('-processed_at')[:10]
    
    from apps.accounts.models import Company
    context = {
        'pending_emails': emails,
        'recent_emails': recent,
        'companies': Company.objects.filter(tenant=request.user.tenant),
    }
    return render(request, 'ai_assistant/pending_inventory.html', context)


@login_required
@require_POST
def approve_pending_item(request, item_id):
    """Approve a single pending inventory item — creates real InventoryItem"""
    from apps.inventory.models import InventoryItem, Warehouse
    
    item = get_object_or_404(PendingInventoryItem, id=item_id, email__tenant=request.user.tenant)
    
    if item.status != 'pending':
        return JsonResponse({'error': 'Item already processed'}, status=400)
    
    # Find or create a default warehouse
    warehouse = Warehouse.objects.filter(tenant=request.user.tenant, is_active=True).first()
    if not warehouse:
        return JsonResponse({'error': 'No active warehouse found'}, status=400)
    
    # Generate unique SKU
    import time
    sku = f"EML-{int(time.time()) % 99999:05d}"
    
    # Manual company override
    company_id = request.POST.get('company_id')
    supplier = item.email.matched_company
    if company_id:
        from apps.accounts.models import Company
        supplier = Company.objects.filter(id=company_id, tenant=request.user.tenant).first()

    # Create real inventory item
    inv_item = InventoryItem.objects.create(
        tenant=request.user.tenant,
        sku=sku,
        product_name=item.product_name,
        description=item.description,
        warehouse=warehouse,
        quantity=item.quantity or 0,
        unit_of_measure=item.unit or 'lbs',
        unit_cost=item.price or 0,
        price_unit=item.price_unit or 'per lbs',
        company=supplier,
    )
    
    item.status = 'approved'
    item.created_inventory_item = inv_item
    item.save()
    
    # Check if all items in email are processed
    email = item.email
    if not email.items.filter(status='pending').exists():
        email.status = 'approved'
        email.processed_at = timezone.now()
        email.processed_by = request.user
        email.save()
    
    return JsonResponse({'status': 'approved', 'sku': sku})


@login_required
@require_POST
def reject_pending_item(request, item_id):
    """Reject a single pending inventory item"""
    item = get_object_or_404(PendingInventoryItem, id=item_id, email__tenant=request.user.tenant)
    item.status = 'rejected'
    item.save()
    
    email = item.email
    if not email.items.filter(status='pending').exists():
        has_approved = email.items.filter(status='approved').exists()
        email.status = 'partial' if has_approved else 'rejected'
        email.processed_at = timezone.now()
        email.processed_by = request.user
        email.save()
    
    return JsonResponse({'status': 'rejected'})


@login_required
@require_POST
def approve_all_items(request, email_id):
    """Bulk approve all pending items from an email"""
    from apps.inventory.models import InventoryItem, Warehouse
    email = get_object_or_404(PendingInventoryEmail, id=email_id, tenant=request.user.tenant)
    
    warehouse = Warehouse.objects.filter(tenant=request.user.tenant, is_active=True).first()
    if not warehouse:
        return JsonResponse({'error': 'No active warehouse found'}, status=400)
    
    # Manual company override for all items in this email
    company_id = request.POST.get('company_id')
    supplier = email.matched_company
    if company_id:
        from apps.accounts.models import Company
        supplier = Company.objects.filter(id=company_id, tenant=request.user.tenant).first()

    import time
    created = 0
    for item in email.items.filter(status='pending'):
        timestamp = int(time.time()) % 100000
        sku = f"EML-{timestamp:05d}-{item.id}"
        inv_item = InventoryItem.objects.create(
            tenant=request.user.tenant,
            sku=sku,
            product_name=item.product_name,
            description=item.description,
            warehouse=warehouse,
            quantity=item.quantity or 0,
            unit_of_measure=item.unit or 'lbs',
            unit_cost=item.price or 0,
            price_unit=item.price_unit or 'per lbs',
            company=supplier,
        )
        item.status = 'approved'
        item.created_inventory_item = inv_item
        item.save()
        created += 1
    
    if not email.items.filter(status='pending').exists():
        email.status = 'approved'
        email.processed_at = timezone.now()
        email.processed_by = request.user
        email.save()
    
    return JsonResponse({'status': 'approved', 'count': created})


@login_required
@require_POST
def reject_all_items(request, email_id):
    """Bulk reject all pending items from an email"""
    email = get_object_or_404(PendingInventoryEmail, id=email_id, tenant=request.user.tenant)
    
    updated = email.items.filter(status='pending').update(status='rejected')
    
    email.status = 'rejected'
    email.processed_at = timezone.now()
    email.processed_by = request.user
    email.save()
    
    return JsonResponse({'status': 'rejected', 'count': updated})


# ─── FEATURE C: Smart Matches ───────────────────────────────────────────────

@login_required
def smart_matches_dashboard(request):
    """Show smart demand-supply matches"""
    # Trigger matching engine to ensure fresh results on page load
    from .matching import run_matching
    run_matching(request.user.tenant)
    
    matches = SmartMatch.objects.filter(
        tenant=request.user.tenant,
        is_dismissed=False,
    ).select_related('requirement', 'requirement__buyer', 'inventory_item', 'inventory_item__warehouse')
    
    requirements = BuyerRequirement.objects.filter(
        tenant=request.user.tenant,
        is_fulfilled=False,
    ).select_related('buyer')
    
    context = {
        'matches': matches,
        'requirements': requirements,
    }
    return render(request, 'ai_assistant/smart_matches.html', context)


@login_required
@require_POST
def dismiss_match(request, match_id):
    """Dismiss a smart match"""
    match = get_object_or_404(SmartMatch, id=match_id, tenant=request.user.tenant)
    match.is_dismissed = True
    match.save()
    return JsonResponse({'status': 'dismissed'})


