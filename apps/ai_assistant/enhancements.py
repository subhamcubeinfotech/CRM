from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import DemandForecastSnapshot, QuoteDraft

logger = logging.getLogger('apps.ai_assistant')


PRODUCT_KEYWORDS = {
    'Electronics': ['laptop', 'computer', 'electronic', 'pcb', 'motherboard', 'chip', 'semiconductor', 'battery', 'hardware', 'mobile', 'tablet'],
    'Raw Materials': ['ore', 'metal', 'aluminum', 'copper', 'iron', 'steel', 'scrap', 'mineral', 'alloy', 'brass', 'bronze', 'ingot'],
    'Plastics': ['hdpe', 'ldpe', 'pet', 'pp', 'pvc', 'abs', 'plastic', 'regrind', 'flake', 'pellet', 'polymer', 'resin', 'polyethylene'],
    'Paper & Cardboard': ['paper', 'cardboard', 'kraft', 'pulp', 'carton', 'corrugated'],
    'Textiles': ['fabric', 'cotton', 'textile', 'polyester', 'yarn', 'cloth', 'fiber'],
    'Machinery': ['pump', 'motor', 'engine', 'tool', 'equipment', 'heavy', 'spare part', 'industrial'],
}


def classify_product_type(*texts: str) -> str:
    """Best-effort classifier for product/material category used by map legends."""
    haystack = ' '.join([t for t in texts if t]).lower()
    if not haystack:
        return 'Other'

    for label, words in PRODUCT_KEYWORDS.items():
        if any(w in haystack for w in words):
            return label
    return 'Other'


def analyze_email_sentiment(subject: str, body: str) -> dict:
    """
    Rule-based urgency/frustration detection for incoming emails.
    Returns sentiment + priority that can be rendered in dashboard badges.
    """
    text = f"{subject or ''} {body or ''}".lower()

    urgent_terms = [
        'urgent', 'asap', 'immediately', 'today', 'right away', 'critical',
        'deadline', 'need now', 'rush', 'priority', 'expedite', 'delay'
    ]
    frustration_terms = [
        'frustrated', 'unacceptable', 'disappointed', 'angry', 'upset',
        'issue not resolved', 'still waiting', 'no response', 'escalate',
        'complaint', 'bad service', 'failure', 'again and again'
    ]
    positive_terms = ['thanks', 'thank you', 'great', 'appreciate', 'happy', 'resolved']

    urgent_hits = sum(1 for t in urgent_terms if t in text)
    frustration_hits = sum(1 for t in frustration_terms if t in text)
    positive_hits = sum(1 for t in positive_terms if t in text)

    score = (urgent_hits * -0.2) + (frustration_hits * -0.35) + (positive_hits * 0.2)
    score = max(min(score, 1.0), -1.0)

    if frustration_hits >= 2 or urgent_hits >= 3:
        priority = 'urgent'
    elif frustration_hits >= 1 or urgent_hits >= 1:
        priority = 'high'
    elif positive_hits >= 2:
        priority = 'low'
    else:
        priority = 'medium'

    if score <= -0.4:
        sentiment = 'negative'
    elif score >= 0.25:
        sentiment = 'positive'
    else:
        sentiment = 'neutral'

    reasons = []
    if urgent_hits:
        reasons.append(f'urgent_terms={urgent_hits}')
    if frustration_hits:
        reasons.append(f'frustration_terms={frustration_hits}')
    if positive_hits:
        reasons.append(f'positive_terms={positive_hits}')

    return {
        'sentiment_label': sentiment,
        'sentiment_score': float(round(score, 3)),
        'priority_level': priority,
        'sentiment_reason': ', '.join(reasons) if reasons else 'No strong emotional signal detected.',
    }


def _quantize(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def refresh_demand_forecasts(tenant, lookback_days: int = 30) -> int:
    """Compute/update demand forecasts and return number of records touched."""
    from apps.inventory.models import InventoryItem, InventoryTransaction

    if not tenant:
        return 0

    cutoff = timezone.now() - timedelta(days=lookback_days)
    items = InventoryItem.objects.filter(tenant=tenant).select_related('warehouse')
    touched = 0

    with transaction.atomic():
        for item in items:
            usage_qs = InventoryTransaction.objects.filter(
                tenant=tenant,
                item=item,
                transaction_type__in=['SHIP', 'RESERVE'],
                timestamp__gte=cutoff,
            )

            # quantity_change is typically negative for outbound; normalize to positive usage.
            usage = Decimal('0')
            for tx in usage_qs:
                change = tx.quantity_change or Decimal('0')
                usage += abs(Decimal(change))

            days = Decimal(str(lookback_days))
            avg_daily = (usage / days) if days > 0 else Decimal('0')

            qty = Decimal(item.available_quantity or 0)
            days_to_runout = None
            predicted_date = None
            confidence = 0.4

            if avg_daily > 0:
                raw_days = int((qty / avg_daily).to_integral_value(rounding=ROUND_HALF_UP))
                days_to_runout = max(raw_days, 0)
                predicted_date = timezone.now().date() + timedelta(days=days_to_runout)
                # More observed usage events -> better confidence
                event_count = usage_qs.count()
                confidence = min(0.95, 0.45 + (event_count / 40.0))

            if days_to_runout is None:
                alert = 'healthy'
                notes = 'Insufficient outbound usage history to estimate depletion.'
            elif days_to_runout <= 7:
                alert = 'critical'
                notes = f'Stock may deplete in {days_to_runout} days.'
            elif days_to_runout <= 15:
                alert = 'risk'
                notes = f'Stock projected to run out in about {days_to_runout} days.'
            elif days_to_runout <= 30:
                alert = 'watch'
                notes = f'Stock watch window: ~{days_to_runout} days left.'
            else:
                alert = 'healthy'
                notes = f'Stock health is stable for approximately {days_to_runout} days.'

            DemandForecastSnapshot.objects.update_or_create(
                tenant=tenant,
                inventory_item=item,
                defaults={
                    'current_quantity': _quantize(qty, '0.01'),
                    'avg_daily_usage': _quantize(avg_daily, '0.0001'),
                    'days_to_runout': days_to_runout,
                    'predicted_runout_date': predicted_date,
                    'confidence_score': float(round(confidence, 3)),
                    'alert_level': alert,
                    'notes': notes,
                },
            )
            touched += 1

    return touched


def build_quote_draft(match, user, markup_percent: Decimal | float | int = Decimal('12.5')):
    """Create or update a quote draft from a SmartMatch."""
    from .models import QuoteDraft

    markup = Decimal(str(markup_percent or 0))
    requirement = match.requirement
    item = match.inventory_item
    quantity = Decimal(requirement.quantity_needed or 0)
    if quantity <= 0:
        quantity = Decimal(item.available_quantity or item.quantity or 0)

    supplier_price = Decimal(item.unit_cost or 0)
    quoted_unit = supplier_price * (Decimal('1') + (markup / Decimal('100')))
    total = quoted_unit * quantity

    supplier_name = item.company.name if item.company else 'Warehouse Stock'
    buyer_name = requirement.buyer.name if requirement.buyer else 'Buyer'
    material_name = requirement.material_name or item.product_name
    unit = requirement.unit or item.unit_of_measure or 'lbs'

    subject = f"Quote for {material_name} - Ref Match #{match.id}"
    body = (
        f"Subject: {subject}\n\n"
        f"Dear {buyer_name},\n\n"
        f"We are pleased to provide you with a formal quote regarding your requirement for {material_name}.\n\n"
        f"Based on our current high-fidelity matching, we have identified a suitable batch from {supplier_name} that meets your specifications. Details of our offer are as follows:\n\n"
        f"• Material: {material_name}\n"
        f"• Quantity: {quantity} {unit}\n"
        f"• Quote Price: ${quoted_unit:.4f} per {unit}\n"
        f"• Total Estimated Value: ${total:.2f}\n\n"
        f"This quote is valid for 48 hours. Please let us know if you wish to proceed with the allocation and dispatch scheduling.\n\n"
        f"We look forward to facilitating this transaction for you.\n\n"
        f"Best regards,\n"
        f"The FreightPro AI Logistics Team"
    )

    draft, _ = QuoteDraft.objects.update_or_create(
        tenant=match.tenant,
        smart_match=match,
        defaults={
            'requirement': requirement,
            'inventory_item': item,
            'buyer': requirement.buyer,
            'supplier': item.company,
            'quantity': _quantize(quantity, '0.01'),
            'unit': unit,
            'supplier_unit_price': _quantize(supplier_price, '0.0001'),
            'markup_percent': _quantize(markup, '0.01'),
            'quoted_unit_price': _quantize(quoted_unit, '0.0001'),
            'total_amount': _quantize(total, '0.01'),
            'subject': subject,
            'body_text': body,
            'status': 'draft',
            'created_by': user,
        },
    )

    return draft


def send_quote_draft(draft: QuoteDraft) -> tuple[bool, str]:
    """Send quote draft email to buyer and update status."""
    buyer = draft.buyer
    if not buyer or not buyer.email:
        return False, 'Buyer email not configured.'

    try:
        send_mail(
            subject=draft.subject,
            message=draft.body_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[buyer.email],
        )
        draft.status = 'sent'
        draft.sent_at = timezone.now()
        draft.save(update_fields=['status', 'sent_at', 'updated_at'])
        return True, f'Quote sent to {buyer.email}'
    except Exception as exc:
        logger.error('Failed to send quote draft %s: %s', draft.id, exc)
        return False, 'Quote email delivery failed.'


def _extract_json_block(text: str) -> dict:
    if not text:
        return {}
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def extract_document_with_ai(file_bytes: bytes, filename: str, mime_type: str | None = None) -> dict:
    """OCR/vision extraction with OpenAI fallback + regex safety net."""
    mime_type = mime_type or mimetypes.guess_type(filename)[0] or 'image/jpeg'
    api_key = getattr(settings, 'OPENAI_API_KEY', '')

    if api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            b64 = base64.b64encode(file_bytes).decode('utf-8')
            data_url = f"data:{mime_type};base64,{b64}"

            prompt = (
                'You are a logistics OCR assistant. Read this document image and return JSON only with keys: '
                'raw_text, document_type, invoice_number, bol_number, date, supplier, buyer, items, total_amount. '
                'For items use list of objects with description, quantity, unit, unit_price.'
            )

            response = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': prompt},
                            {'type': 'image_url', 'image_url': {'url': data_url}},
                        ],
                    }
                ],
                response_format={'type': 'json_object'},
                temperature=0,
            )

            payload = json.loads(response.choices[0].message.content)
            raw_text = payload.get('raw_text', '') or ''
            confidence = 0.85 if raw_text else 0.55
            return {
                'status': 'completed',
                'confidence_score': confidence,
                'extracted_text': raw_text,
                'extracted_json': payload,
            }
        except Exception as exc:
            logger.error('Document vision extraction failed for %s: %s', filename, exc)

    # Regex/text fallback when AI key is unavailable.
    decoded = file_bytes.decode('utf-8', errors='ignore') if mime_type.startswith('text/') else ''
    invoice_match = re.search(r'(invoice\s*(?:no|#|number)?\s*[:\-]?\s*[A-Z0-9\-\/]+)', decoded, re.I)
    bol_match = re.search(r'(?:bol|bill\s*of\s*lading)\s*(?:no|#|number)?\s*[:\-]?\s*([A-Z0-9\-\/]+)', decoded, re.I)
    total_match = re.search(r'(?:total|amount\s*due)\s*[:\-]?\s*\$?([0-9,]+(?:\.[0-9]{1,2})?)', decoded, re.I)

    data = {
        'raw_text': decoded[:4000],
        'document_type': 'unknown',
        'invoice_number': invoice_match.group(0) if invoice_match else '',
        'bol_number': bol_match.group(1) if bol_match else '',
        'total_amount': total_match.group(1) if total_match else '',
        'items': [],
    }

    return {
        'status': 'completed' if decoded else 'failed',
        'confidence_score': 0.35 if decoded else 0.0,
        'extracted_text': decoded[:4000],
        'extracted_json': data,
        'error_message': '' if decoded else 'No OCR provider configured. Add OPENAI_API_KEY for image OCR.',
    }
