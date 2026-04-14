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


def extract_inventory_items(body_text):
    """
    Rule-based extraction of inventory items from email text.
    Looks for patterns like:
    - Product Name: HDPE, Qty: 40,000 lbs, Price: $0.45/lb
    - 40,000 lbs of HDPE at $0.45 per lb
    - HDPE Regrind | 40,000 lbs | $0.45/lb
    """
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

    # Search for unread emails (can be customized with labels/filters)
    status, messages = mail.search(None, 'UNSEEN')
    if status != 'OK':
        logger.error("Failed to search inbox")
        mail.logout()
        return 0

    email_ids = messages[0].split()[-max_emails:]  # Get latest N
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
        extracted_items = extract_inventory_items(body)
        if not extracted_items:
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
