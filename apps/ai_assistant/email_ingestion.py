"""
Email Ingestion Utility - Fetches supplier emails via IMAP and extracts inventory data.
Uses rule-based parsing (upgradeable to LLM when API key is available).
"""
import imaplib
import email
import re
import json
import logging
from email.header import decode_header
from datetime import datetime

from django.utils import timezone
from django.conf import settings

logger = logging.getLogger('apps.ai_assistant')


def connect_imap():
    """Connect to Gmail IMAP server using credentials from .env"""
    host = getattr(settings, 'EMAIL_IMAP_HOST', 'imap.gmail.com')
    port = int(getattr(settings, 'EMAIL_IMAP_PORT', 993))
    username = getattr(settings, 'EMAIL_HOST_USER', '')
    password = getattr(settings, 'EMAIL_HOST_PASSWORD', '')

    if not username or not password:
        raise ValueError(
            "Email credentials not configured. Add EMAIL_HOST_USER and EMAIL_HOST_PASSWORD to .env"
        )

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(username, password)
    return mail


def decode_email_subject(msg):
    """Decode email subject"""
    subject, encoding = decode_header(msg['Subject'])[0]
    if isinstance(subject, bytes):
        subject = subject.decode(encoding or 'utf-8', errors='replace')
    return subject


def get_email_body(msg):
    """Extract text body from email"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                except:
                    body = str(part.get_payload())
                break
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='replace')
        except:
            body = str(msg.get_payload())
    return body


def extract_inventory_items_llm(body_text):
    """
    Uses OpenAI LLM to extract inventory items from unstructured email text.
    """
    from openai import OpenAI
    
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if not api_key or api_key.startswith('fb2a'):  # Check for placeholder
        return []

    client = OpenAI(api_key=api_key)
    
    prompt = f"""
    Extract inventory items from the following email text into a JSON list.
    Each item must have: product_name, quantity, unit (lbs, kgs, etc), price (as number), price_unit (e.g. per lb).
    
    Email Text:
    {body_text}
    
    JSON Output format: {{"items": [{{"product_name": "...", "quantity": 0, "unit": "...", "price": 0, "price_unit": "..."}}]}}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "You are an inventory data extraction assistant. Output ONLY valid JSON."},
                      {"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        data = json.loads(response.choices[0].message.content)
        return data.get('items', data.get('inventory', []))
    except Exception as e:
        logger.error(f"LLM Extraction failed: {e}")
        return []


def handle_attachments(msg):
    """
    Extract text or data from PDF/CSV attachments.
    For now, return text from text-based attachments.
    """
    attachment_text = ""
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get('Content-Disposition') is None:
            continue
            
        filename = part.get_filename()
        content_type = part.get_content_type()
        
        if filename:
            payload = part.get_payload(decode=True)
            if content_type == 'text/csv' or filename.endswith('.csv'):
                attachment_text += f"\n[CSV FILE: {filename}]\n" + payload.decode('utf-8', errors='replace')
            elif content_type == 'application/pdf' or filename.endswith('.pdf'):
                # In a real setup, use pdfplumber or similar.
                # For now, acknowledge the PDF and try to extract what's possible
                attachment_text += f"\n[PDF FILE: {filename}] (Processing text content...)\n"
    return attachment_text


def extract_inventory_items(body_text):
    """
    Tries LLM extraction first, falls back to Rule-based.
    """
    # 1. Try LLM first if API key exists
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if api_key and not api_key.startswith('fb2a'):
        llm_items = extract_inventory_items_llm(body_text)
        if llm_items:
            return llm_items

    # 2. Fallback to Regex
    items = []
    
    # Pattern 1: Pipe/dash separated (common in vendor lists)
    pipe_lines = re.findall(
        r'(.+?)\s*[\|–-]\s*([\d,]+\.?\d*)\s*(lbs?|kgs?|MT|tons?|pcs)\s*[\|–-]\s*\$?([\d,]+\.?\d*)\s*/?\s*(lb|kg|ton|pc)?',
        body_text, re.IGNORECASE
    )
    for match in pipe_lines:
        items.append({
            'product_name': match[0].strip(),
            'quantity': float(match[1].replace(',', '')),
            'unit': match[2],
            'price': float(match[3].replace(',', '')),
            'price_unit': f'per {match[4]}' if match[4] else 'per lb',
        })

    # Pattern 2: "X lbs of Product at $Y per lb"
    quantity_of = re.findall(
        r'([\d,]+\.?\d*)\s*(lbs?|kgs?|MT|tons?)\s+(?:of\s+)?(.+?)\s+(?:at|@)\s+\$?([\d,]+\.?\d*)\s*/?\s*(lb|kg|ton)?',
        body_text, re.IGNORECASE
    )
    for match in quantity_of:
        items.append({
            'product_name': match[2].strip(),
            'quantity': float(match[0].replace(',', '')),
            'unit': match[1],
            'price': float(match[3].replace(',', '')),
            'price_unit': f'per {match[4]}' if match[4] else 'per lb',
        })

    # Pattern 3: Simple "Product: X, Qty: Y, Price: Z" style
    structured = re.findall(
        r'(?:product|item|material)\s*:\s*(.+?)(?:\n|,)\s*(?:qty|quantity|weight)\s*:\s*([\d,]+\.?\d*)\s*(lbs?|kgs?|MT)?\s*(?:\n|,)\s*(?:price|cost|rate)\s*:\s*\$?([\d,]+\.?\d*)',
        body_text, re.IGNORECASE
    )
    for match in structured:
        items.append({
            'product_name': match[0].strip(),
            'quantity': float(match[1].replace(',', '')),
            'unit': match[2] or 'lbs',
            'price': float(match[3].replace(',', '')),
            'price_unit': 'per lb',
        })

    # Deduplicate by product_name
    seen = set()
    unique_items = []
    for item in items:
        key = item['product_name'].lower()
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    return unique_items


def fetch_and_process_emails(tenant, max_emails=10):
    """
    Main entry point: connect to IMAP, fetch new emails, extract inventory items.
    Returns count of processed emails.
    """
    from .models import PendingInventoryEmail, PendingInventoryItem
    from apps.accounts.models import Company

    try:
        mail = connect_imap()
    except Exception as e:
        logger.error(f"Failed to connect to IMAP: {e}")
        return 0

    mail.select('INBOX')

    # Search for all emails from the last 24 hours (even if seen) for debugging
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
    status, messages = mail.search(None, f'(SINCE {yesterday})')
    if status != 'OK':
        logger.error("Failed to search inbox")
        mail.logout()
        return 0

    email_ids = messages[0].split()
    email_ids = email_ids[-max_emails:]  # Get latest N
    processed = 0

    for eid in email_ids:
        status, msg_data = mail.fetch(eid, '(RFC822)')
        if status != 'OK':
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_email_subject(msg)
        sender = email.utils.parseaddr(msg['From'])
        body = get_email_body(msg)

        # Skip if already processed
        if PendingInventoryEmail.objects.filter(
            tenant=tenant, subject=subject, sender_email=sender[1]
        ).exists():
            continue

        # Extract inventory items
        try:
            print(f"DEBUG: Checking email: '{subject}' from {sender[1]}")
        except:
            print(f"DEBUG: Checking email: [Subject with special chars] from {sender[1]}")

        extracted_items = extract_inventory_items(body)
        if not extracted_items:
            print(f"DEBUG: Skipped '{subject}' - No items found. Body starts with: {body[:50].strip()}...")
            continue  # Skip emails without inventory data

        # Try to match sender to a Company
        matched_company = Company.objects.filter(
            tenant=tenant,
            is_active=True,
            email__icontains=sender[1].split('@')[0]
        ).first()

        # Create pending email record
        pending_email = PendingInventoryEmail.objects.create(
            tenant=tenant,
            sender_email=sender[1],
            sender_name=sender[0],
            subject=subject,
            body_text=body,
            received_at=timezone.now(),
            matched_company=matched_company,
            raw_extraction=extracted_items,
        )

        # Create pending items
        for item_data in extracted_items:
            PendingInventoryItem.objects.create(
                email=pending_email,
                product_name=item_data.get('product_name', ''),
                quantity=item_data.get('quantity'),
                unit=item_data.get('unit', 'lbs'),
                price=item_data.get('price'),
                price_unit=item_data.get('price_unit', 'per lb'),
                material_type=item_data.get('material_type', ''),
                grade=item_data.get('grade', ''),
                location=item_data.get('location', ''),
            )

        processed += 1
        logger.info(f"Processed email: {subject} ({len(extracted_items)} items)")

    mail.logout()
    return processed
