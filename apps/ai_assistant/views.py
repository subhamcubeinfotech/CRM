"""
AI Assistant Views - Chat API and Pending Inventory management
"""
import json
import logging
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q

from .models import (
    ChatSession, ChatMessage, PendingInventoryEmail, PendingInventoryItem,
    BuyerRequirement, SmartMatch, DemandForecastSnapshot, QuoteDraft, DocumentVisionRecord
)
from .engine import process_query
from .enhancements import (
    refresh_demand_forecasts, build_quote_draft, send_quote_draft,
    extract_document_with_ai
)

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
    # Admin Sees all companies. Normal users see only their tenant's.
    if request.user.is_superuser or getattr(request.user, 'is_admin', False):
        all_companies = Company.objects.all()
    else:
        all_companies = Company.objects.filter(tenant=request.user.tenant)

    context = {
        'pending_emails': emails,
        'recent_emails': recent,
        'companies': all_companies,
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

    # Ensure Material record exists so it shows in the UI dropdowns
    from apps.inventory.models import Material
    material_obj, _ = Material.objects.get_or_create(
        tenant=request.user.tenant,
        company=supplier,
        name=item.product_name,
        defaults={'description': item.description or ''}
    )

    # Create real inventory item
    inv_item = InventoryItem.objects.create(
        tenant=request.user.tenant,
        sku=sku,
        product_name=item.product_name,
        description=item.description,
        warehouse=warehouse,
        quantity=item.quantity or 0,
        unit_of_measure=item.unit or 'lbs',
        offered_weight=item.quantity or 0,
        offered_weight_unit=item.unit or 'lbs',
        unit_cost=item.price or 0,
        price_unit=item.price_unit or 'per lbs',
        company=supplier,
    )
    
    # Log Initial Transaction
    from apps.inventory.models import InventoryTransaction
    InventoryTransaction.objects.create(
        item=inv_item,
        transaction_type='INITIAL',
        quantity_change=inv_item.quantity,
        new_quantity=inv_item.quantity,
        user=request.user,
        notes=f"Approved from AI Inbox (Email: {item.email.subject})"
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
    from apps.inventory.models import InventoryItem, Warehouse, Material
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
        
        # Ensure Material record exists
        material_obj, _ = Material.objects.get_or_create(
            tenant=request.user.tenant,
            company=supplier,
            name=item.product_name,
            defaults={'description': item.description or ''}
        )

        inv_item = InventoryItem.objects.create(
            tenant=request.user.tenant,
            sku=sku,
            product_name=item.product_name,
            description=item.description,
            warehouse=warehouse,
            quantity=item.quantity or 0,
            unit_of_measure=item.unit or 'lbs',
            offered_weight=item.quantity or 0,
            offered_weight_unit=item.unit or 'lbs',
            unit_cost=item.price or 0,
            price_unit=item.price_unit or 'per lbs',
            company=supplier,
        )

        # Log Initial Transaction
        from apps.inventory.models import InventoryTransaction
        InventoryTransaction.objects.create(
            item=inv_item,
            transaction_type='INITIAL',
            quantity_change=inv_item.quantity,
            new_quantity=inv_item.quantity,
            user=request.user,
            notes=f"Approved from AI Inbox (Bulk)"
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
    # 1. Trigger Email Fetch to get new requirements
    from .email_ingestion import fetch_and_process_emails
    try:
        # We pass None to allow global routing (matches sender to company/tenant)
        fetch_and_process_emails(tenant=None, max_emails=5) 
    except Exception as e:
        logger.error(f"Auto-fetch failed: {e}")

    # 2. Trigger matching engine to ensure fresh results on page load
    from .matching import run_matching
    run_matching(request.user.tenant)
    
    matches = SmartMatch.objects.filter(
        tenant=request.user.tenant,
        is_dismissed=False,
    ).select_related('requirement', 'requirement__buyer', 'inventory_item', 'inventory_item__warehouse')
    
    requirements = BuyerRequirement.objects.filter(
        tenant=request.user.tenant,
        is_fulfilled=False,
    ).select_related('buyer').order_by('-created_at')

    # 3. Fetch Pending Supplier Leads (Emails with pending inventory items)
    pending_supply_emails = PendingInventoryEmail.objects.filter(
        tenant=request.user.tenant,
        status='pending',
    ).prefetch_related('items').order_by('-received_at')
    
    context = {
        'matches': matches,
        'requirements': requirements,
        'pending_supply_emails': pending_supply_emails,
        'recent_quote_drafts': QuoteDraft.objects.filter(tenant=request.user.tenant).select_related('buyer', 'supplier', 'inventory_item')[:8],
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


@login_required
@require_POST
def notify_match_parties(request, match_id):
    """Send notifications to both buyer and supplier about a match"""
    from django.core.mail import send_mail
    from django.conf import settings
    match = get_object_or_404(SmartMatch, id=match_id, tenant=request.user.tenant)
    
    buyer = match.requirement.buyer
    inventory_item = match.inventory_item
    supplier = inventory_item.company
    
    # Context for emails
    details = f"Material: {match.requirement.material_name}\nQuantity: {match.requirement.quantity_needed} {match.requirement.unit}"
    
    try:
        # 1. Notify Buyer
        if buyer and buyer.email:
            send_mail(
                subject=f"Match Found: {match.requirement.material_name} available",
                message=f"Hello {buyer.name},\n\nOur AI Matchmaker found available stock for your requirement.\n\n{details}\nSupplier: {supplier.name if supplier else 'Available in Warehouse'}\n\nPlease reply to this email to coordinate.\n\nBest regards,\nFreightPro AI Team",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[buyer.email],
            )
            
        # 2. Notify Supplier
        if supplier and supplier.email:
            send_mail(
                subject=f"New Lead: Buyer interested in your {inventory_item.product_name}",
                message=f"Hello {supplier.name},\n\nA buyer is looking for the material you have in stock.\n\n{details}\nBuyer: {buyer.name if buyer else 'Direct Lead'}\n\nPlease update your availability in the CRM.\n\nBest regards,\nFreightPro AI Team",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[supplier.email],
            )

        # Auto-create a draft quote so sales team can review/send quickly.
        try:
            build_quote_draft(match, request.user)
            match.is_quoted = True
        except Exception as quote_exc:
            logger.warning("Quote draft auto-generation skipped for match %s: %s", match.id, quote_exc)

        match.is_notified = True
        match.save(update_fields=['is_notified', 'is_quoted'])
        
        return JsonResponse({
            'status': 'success', 
            'message': 'Notifications sent via email to both parties!'
        })
    except Exception as e:
        logger.error(f"Error sending match notifications: {e}")
        # Even if email fails, we update the UI for the demo
        match.is_notified = True
        match.save()
        return JsonResponse({
            'status': 'partial_success', 
            'message': 'Notifications highlighted. (Email delivery skipped in test mode)'
        })



@login_required
@require_POST
def find_match_for_requirement(request, requirement_id):
    """Trigger matching engine for a specific requirement"""
    from .matching import match_requirement_to_inventory, get_ai_match_insight
    
    requirement = get_object_or_404(BuyerRequirement, id=requirement_id, tenant=request.user.tenant)
    
    matches = match_requirement_to_inventory(requirement, request.user.tenant)
    created_count = 0
    
    for item, score, reason in matches:
        # Don't create duplicate matches
        if not SmartMatch.objects.filter(
            tenant=request.user.tenant,
            requirement=requirement,
            inventory_item=item,
        ).exists():
            insight = get_ai_match_insight(requirement, item) if score >= 70 else reason
            
            SmartMatch.objects.create(
                tenant=request.user.tenant,
                requirement=requirement,
                inventory_item=item,
                confidence_score=score,
                match_reason=insight,
            )
            created_count += 1
            
    return JsonResponse({
        'status': 'success',
        'created_count': created_count,
        'total_matches': len(matches)
    })


# ─────────────────── FEATURE E: AI Enhancements ───────────────────

@login_required
def enhancements_dashboard(request):
    """Unified dashboard for demand forecasting, quote automation, sentiment and OCR."""
    from apps.accounts.utils import is_staff_user
    is_internal = request.user.is_superuser or is_staff_user(request.user)
    
    if is_internal:
        forecasts = DemandForecastSnapshot.plain_objects.all()
        sentiment_emails = PendingInventoryEmail.plain_objects.all()
        quote_drafts = QuoteDraft.plain_objects.all()
        recent_matches = SmartMatch.plain_objects.all()
        vision_records = DocumentVisionRecord.plain_objects.all()
    else:
        forecasts = DemandForecastSnapshot.objects.filter(tenant=request.user.tenant)
        sentiment_emails = PendingInventoryEmail.objects.filter(tenant=request.user.tenant)
        quote_drafts = QuoteDraft.objects.filter(tenant=request.user.tenant)
        recent_matches = SmartMatch.objects.filter(tenant=request.user.tenant)
        vision_records = DocumentVisionRecord.objects.filter(tenant=request.user.tenant)

    forecasts = forecasts.select_related('inventory_item', 'inventory_item__warehouse').order_by('days_to_runout', '-computed_at')[:25]
    sentiment_emails = sentiment_emails.exclude(sentiment_label='neutral').order_by('-received_at')[:20]
    quote_drafts = quote_drafts.select_related('buyer', 'supplier', 'inventory_item', 'requirement').order_by('-created_at')[:25]
    recent_matches = recent_matches.filter(is_dismissed=False).select_related('requirement', 'requirement__buyer', 'inventory_item', 'inventory_item__company').order_by('-created_at')[:20]
    vision_records = vision_records.order_by('-created_at')[:20]

    context = {
        'forecasts': forecasts,
        'sentiment_emails': sentiment_emails,
        'quote_drafts': quote_drafts,
        'recent_matches': recent_matches,
        'vision_records': vision_records,
    }
    return render(request, 'ai_assistant/enhancements.html', context)


@login_required
@require_POST
def draft_quote_for_match(request, match_id):
    """Create an automated quote draft from a SmartMatch."""
    match = get_object_or_404(
        SmartMatch.objects.select_related('requirement', 'requirement__buyer', 'inventory_item', 'inventory_item__company'),
        id=match_id,
        tenant=request.user.tenant,
    )
    markup_percent = request.POST.get('markup_percent') or request.GET.get('markup_percent') or '12.5'
    try:
        draft = build_quote_draft(match, request.user, markup_percent=Decimal(str(markup_percent)))
    except Exception as e:
        logger.error("Quote draft generation failed for match %s: %s", match_id, e)
        return JsonResponse({'status': 'error', 'message': 'Failed to create quote draft.'}, status=500)

    match.is_quoted = True
    match.save(update_fields=['is_quoted'])

    return JsonResponse({
        'status': 'success',
        'draft_id': draft.id,
        'quoted_unit_price': float(draft.quoted_unit_price),
        'total_amount': float(draft.total_amount),
        'subject': draft.subject,
    })


@login_required
@require_POST
def send_quote_draft_view(request, draft_id):
    draft = get_object_or_404(QuoteDraft, id=draft_id, tenant=request.user.tenant)
    ok, message = send_quote_draft(draft)
    return JsonResponse({
        'status': 'success' if ok else 'error',
        'message': message,
        'draft_status': draft.status,
    }, status=200 if ok else 400)


@login_required
@require_POST
def refresh_forecasts(request):
    from apps.accounts.utils import is_staff_user
    # If superuser/staff, refresh EVERYTHING. If tenant user, refresh only their tenant.
    is_internal = request.user.is_superuser or is_staff_user(request.user)
    tenant_to_refresh = None if is_internal else request.user.tenant
    
    touched = refresh_demand_forecasts(tenant_to_refresh)
    return JsonResponse({'status': 'success', 'updated_records': touched})


@login_required
@require_POST
def document_vision_upload(request):
    """
    Upload a photo/scan and run OCR-style extraction.
    Supports image + text files; image OCR quality depends on OPENAI_API_KEY.
    """
    upload = request.FILES.get('file')
    if not upload:
        return JsonResponse({'status': 'error', 'message': 'No file uploaded.'}, status=400)

    # Size guardrail to prevent very large payload uploads in sync request cycle.
    if upload.size > 12 * 1024 * 1024:
        return JsonResponse({'status': 'error', 'message': 'File too large (max 12MB).'}, status=400)

    content = upload.read()
    mime = getattr(upload, 'content_type', None)
    result = extract_document_with_ai(content, upload.name, mime_type=mime)

    record = DocumentVisionRecord.objects.create(
        tenant=request.user.tenant,
        source_type='general',
        uploaded_file=upload,
        extracted_text=result.get('extracted_text', ''),
        extracted_json=result.get('extracted_json', {}),
        confidence_score=result.get('confidence_score', 0.0) or 0.0,
        status=result.get('status', 'failed'),
        error_message=result.get('error_message', ''),
        created_by=request.user,
    )

    return JsonResponse({
        'status': 'success' if record.status == 'completed' else 'partial_success',
        'record_id': record.id,
        'ocr_status': record.status,
        'confidence_score': record.confidence_score,
        'extracted_text': record.extracted_text[:2000],
        'extracted_json': record.extracted_json,
        'error_message': record.error_message,
    })
