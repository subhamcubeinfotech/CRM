"""
Email Ingestion Utility - Fetches supplier emails via IMAP and extracts inventory data.
Uses rule-based parsing (upgradeable to LLM when API key is available).
"""
import imaplib
import email
import email.utils
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
    Handles multiple items, different units, and cleans up common email garbage.
    """
    from openai import OpenAI
    
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if not api_key or api_key.startswith('fb2a'):
        logger.warning("OpenAI API key missing or placeholder. Skipping LLM extraction.")
        return []

    client = OpenAI(api_key=api_key)
    
    prompt = f"""
    You are a logistics and inventory data specialist. Extract all available inventory items from the following email.
    Identify:
    - product_name: Full descriptive name of the material.
    - quantity: Numerical value (handle commas and digits).
    - unit: Weight or count unit (lbs, kgs, MT, etc.).
    - price: Unit price if available.
    - price_unit: Unit for the price (e.g., per lb, per ton).
    - material_type: Category (e.g., Plastic, Metal).
    - location: Where the item is if mentioned.

    If an item is mentioned as "Needed" or "Looking for", do NOT include it here (that is a requirement, not inventory).
    ONLY include items that the sender HAS for sale or in stock.

    Email Content:
    ---
    {body_text}
    ---

    Respond ONLY with a JSON object in this format:
    {{
      "items": [
        {{
          "product_name": "...", 
          "quantity": 0.0, 
          "unit": "...", 
          "price": 0.0, 
          "price_unit": "...",
          "material_type": "...",
          "location": "..."
        }}
      ]
    }}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You extract structured inventory data from business emails. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={ "type": "json_object" },
            temperature=0
        )
        data = json.loads(response.choices[0].message.content)
        return data.get('items', [])
    except Exception as e:
        logger.error(f"LLM Extraction failed: {e}")
        return []


def handle_attachments(msg):
    """
    Extract text or data from PDF/CSV attachments.
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
                try:
                    attachment_text += f"\n[CSV FILE: {filename}]\n" + payload.decode('utf-8', errors='replace')
                except Exception as e:
                    logger.warning(f"Could not decode CSV {filename}: {e}")
            elif content_type == 'application/pdf' or filename.endswith('.pdf'):
                # In a real setup, use pypdf or pdfplumber.
                # Since we want it 'end-to-end', let's assume raw text might be available in some cases
                # or just record the presence for future processing integration.
                attachment_text += f"\n[PDF FILE ATTACHED: {filename}]"
    return attachment_text


def extract_inventory_items(body_text):
    """
    Tries LLM extraction first, falls back to Rule-based.
    """
    # 1. Try LLM first
    llm_items = extract_inventory_items_llm(body_text)
    if llm_items:
        return llm_items

    # 2. Fallback to Regex (already defined below)
    return extract_inventory_items_fallback(body_text)


def extract_inventory_items_fallback(body_text):
    """Enhanced Regex-based extraction patterns"""
    items = []
    
    # Pattern 1: Pipe/dash separated
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

    # Deduplicate by product_name
    seen = set()
    unique_items = []
    for item in items:
        name = str(item.get('product_name', ''))
        key = name.lower()
        if key and key not in seen:
            seen.add(key)
            unique_items.append(item)

    return unique_items


def fetch_and_process_emails(tenant, max_emails=10, request_user=None):
    """
    Main entry point: connect to IMAP, fetch new emails, extract inventory items.
    """
    from .models import PendingInventoryEmail, PendingInventoryItem
    from apps.accounts.models import Company

    try:
        mail = connect_imap()
    except Exception as e:
        logger.error(f"IMAP Connection failed: {e}")
        return 0

    mail.select('INBOX')

    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=2)).strftime("%d-%b-%Y")
    status, messages = mail.search(None, f'(SINCE {yesterday})')
    
    if status != 'OK':
        mail.logout()
        return 0

    email_ids = messages[0].split()
    email_ids = email_ids[-max_emails:]
    processed = 0

    for eid in email_ids:
        try:
            status, msg_data = mail.fetch(eid, '(RFC822)')
            if status != 'OK' or not msg_data: continue

            # msg_data[0] is (b'UID (RFC822 {size}', b'raw_body')
            raw_email = msg_data[0][1]
            if not isinstance(raw_email, bytes):
                continue
                
            msg = email.message_from_bytes(raw_email)
            subject = decode_email_subject(msg)
            sender_raw = msg.get('From', '')
            sender_name, sender_email = email.utils.parseaddr(sender_raw)
        
        except Exception as e:
            logger.error(f"Error fetching email {eid}: {e}")
            continue
        if PendingInventoryEmail.objects.filter(tenant=tenant, subject=subject, sender_email=sender_email).exists():
            continue

        body = get_email_body(msg)
        attachments_info = handle_attachments(msg)
        full_text = body + "\n" + attachments_info

        extracted_items = extract_inventory_items(full_text)
        if not extracted_items:
            continue

        # Intelligent Company Matching
        # First by email domain, then by sender name fuzzy match
        domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ''
        matched_company = None
        
        if domain:
            matched_company = Company.objects.filter(tenant=tenant, email__icontains=domain).first()
            
            # Fallback: Check if any Contact (User) has this email domain
            if not matched_company:
                from django.contrib.auth import get_user_model
                ContactUser = get_user_model()
                contact = ContactUser.objects.filter(tenant=tenant, email__icontains=domain, company__isnull=False).first()
                if contact:
                    matched_company = contact.company
            
        if not matched_company and sender_name:
            s_name = str(sender_name)
            matched_company = Company.objects.filter(tenant=tenant, name__icontains=s_name[:10]).first()

        # Assign Owner: Priority 1 = Company Creator, Priority 2 = Requesting User
        fetched_by = matched_company.created_by if matched_company and matched_company.created_by else request_user

        pending_email = PendingInventoryEmail.objects.create(
            tenant=tenant,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body_text=body,
            received_at=timezone.now(),
            matched_company=matched_company,
            raw_extraction=extracted_items,
            fetched_by=fetched_by,
        )

        for item_data in extracted_items:
            PendingInventoryItem.objects.create(
                email=pending_email,
                product_name=item_data.get('product_name', 'Unknown Material'),
                quantity=item_data.get('quantity'),
                unit=item_data.get('unit', 'lbs'),
                price=item_data.get('price'),
                price_unit=item_data.get('price_unit', 'per lb'),
                material_type=item_data.get('material_type', ''),
                location=item_data.get('location', ''),
            )

        processed += 1

    mail.logout()
    return processed
