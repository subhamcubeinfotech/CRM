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


def html_to_text(html):
    """Simple HTML to text converter using regex"""
    if not html:
        return ""
    # Remove script and style elements
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all other tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Handle common entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def get_email_body(msg):
    """Extract text body from email - improved for HTML emails"""
    body = ""
    html_body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition', ''))
            
            # Skip attachments
            if 'attachment' in content_disposition:
                continue
                
            if content_type == 'text/plain':
                try:
                    plain_text = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    if plain_text.strip():
                        body = plain_text
                except Exception as e:
                    logger.warning(f"Error decoding plain text: {e}")
                    try:
                        body = str(part.get_payload())
                    except:
                        pass
                        
            elif content_type == 'text/html' and not html_body:
                try:
                    html_text = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    if html_text.strip():
                        # Enhanced HTML to text conversion
                        html_body = html_to_text(html_text)
                except Exception as e:
                    logger.warning(f"Error decoding HTML text: {e}")
        
        # Prefer plain text, fall back to converted HTML
        final_body = body if body.strip() else html_body
        
    else:
        # Single part email
        content_type = msg.get_content_type()
        try:
            raw_body = msg.get_payload(decode=True).decode('utf-8', errors='replace')
            if content_type == 'text/html':
                # Convert HTML to text
                import re
                final_body = re.sub(r'<[^>]+>', '', raw_body)
                final_body = re.sub(r'\s+', ' ', final_body).strip()
            else:
                final_body = raw_body
        except Exception as e:
            logger.warning(f"Error decoding single part email: {e}")
            try:
                final_body = str(msg.get_payload())
            except:
                final_body = ""
    
    # Clean up the final body - but don't over-clean if it nukes data
    if final_body:
        # Only remove headers if they are at the very beginning (frequently in forwards)
        lines = final_body.split('\n')
        clean_lines = []
        for line in lines:
            # Skip noise lines but keep content that looks like inventory
            if re.match(r'^(Subject|From|To|Date|Sent):', line, re.I) and not any(kw in line.lower() for kw in ['lbs', 'tons', 'kg', 'scrap', 'material']):
                continue
            clean_lines.append(line)
        
        final_body = '\n'.join(clean_lines)
        final_body = re.sub(r'On .* wrote:', '', final_body)
        final_body = re.sub(r'-{2,}.*?-{2,}', '', final_body, flags=re.DOTALL)
        final_body = re.sub(r'\n{3,}', '\n\n', final_body)
        final_body = final_body.strip()
    
    return final_body or ""


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
    You are a logistics and inventory data specialist. Extract all business materials mentioned in the following email.
    For each item, determine if the sender HAS the material (Selling/Supply) or NEEDS the material (Buying/Demand).
    
    Identify for each item:
    - intent: "supply" (if they are selling/have it) or "demand" (if they are looking for/need it).
    - product_name: Full descriptive name of the material.
    - quantity: Numerical value.
    - unit: Weight or count unit (lbs, kgs, MT, etc.).
    - price: Unit price if available.
    - price_unit: Unit for the price (e.g., per lb, per ton).
    - material_type: Category (e.g., Plastic, Metal).
    - location: Where the item is if mentioned.

    Email Content:
    ---
    {body_text}
    ---

    Respond ONLY with a JSON object in this format:
    {{
      "items": [
        {{
          "intent": "supply|demand",
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
        logger.error(f"LLM Extraction failed: {e}. Falling back to Regex extraction.")
        return extract_items_regex_fallback(body_text)

def extract_items_regex_fallback(body_text):
    """Robust regex fallback for logistics data when LLM is unavailable"""
    import re
    items = []
    
    # 1. Cleaner: Focus on the actual content
    clean_text = body_text.replace('*', '').replace('_', '')
    
    # Identify intent
    is_demand = any(re.search(rf"\b{word}\b", clean_text.lower()) for word in ['require', 'requirement', 'looking for', 'need', 'buy', 'want', 'purchasing'])
    
    # 2. Strategic Patterns
    # Pattern A: [Quantity] [Unit] [Product Name] - Stops before next number/unit pair
    # Pattern B: [Product Name] [Quantity] [Unit]
    patterns = [
        # Catch: 1200 lbs of Aluminum Wire Scrap
        r"([\d,.]+)\s*(?:lbs?|tons?|kg|mt)?\s*(lbs?|tons?|kg|mt)\s*(?:of)?\s*(.*?)(?=\s*[\d,.]+\s*(?:lbs?|tons?|kg|mt)|\.\s|\n|$)",
        # Catch: Aluminum Wire Scrap 1200 lbs
        r"([^.\n\?\!\*,]{3,})\s+([\d,.]+)\s*(lbs?|tons?|kg|mt)",
    ]
    
    for p in patterns:
        for m in re.finditer(p, clean_text, re.IGNORECASE):
            # Sort out which group is quantity vs product
            if m.re.pattern == patterns[0]:
                qty_str, unit, prod = m.group(1), m.group(2), m.group(3)
            else:
                prod, qty_str, unit = m.group(1), m.group(2), m.group(3)
            
            prod = prod.strip()
            if not prod or len(prod) < 3: continue
            
            # Validation: Filter out common non-product noise
            blacklist = ['available', 'hello', 'regards', 'team', 'warehouse', 'any buyers', 'subject', 'fwd', 'date', 'april', 'may', 'june', 'july', '2026', 'from:', 'to:']
            if any(noise in prod.lower() for noise in blacklist):
                 continue
            
            # Only keep if it looks like a material (or has enough words to be a name)
            materials = ['scrap', 'wire', 'aluminum', 'copper', 'plastic', 'metal', 'steel', 'iron', 'brass', 'hms', 'grade']
            if not any(mat in prod.lower() for mat in materials) and len(prod.split()) > 4:
                continue

            try:
                qty = float(qty_str.replace(',', ''))
            except:
                qty = 0.0
                
            items.append({
                "intent": "demand" if is_demand else "supply",
                "product_name": prod,
                "quantity": qty,
                "unit": unit or "lbs",
            })

    # 3. Deduplicate
    seen = set()
    unique_items = []
    for itm in items:
        key = (itm['product_name'].lower()[:30], itm['quantity'])
        if key not in seen:
            seen.add(key)
            unique_items.append(itm)

    return unique_items


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

    # 2. Fallback to Regex
    return extract_items_regex_fallback(body_text)


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
    from .models import PendingInventoryEmail, PendingInventoryItem, BuyerRequirement
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
            message_id = msg.get('Message-ID', f"{subject}-{sender_email}") # Fallback to subject-sender if ID missing
            sender_email = sender_email.lower()

            # SPAM FILTER: Skip common junk domains
            junk_domains = ['jeevansathi.com', 'shaadi.com', 'linkedin.com', 'facebook.com', 'instagram.com', 'noreply', 'notifications']
            if any(junk in sender_email for junk in junk_domains):
                continue
        
        except Exception as e:
            logger.error(f"Error fetching email {eid}: {e}")
            continue
        # GLOBAL Deduplication Check: Use Message-ID for precision
        model_fields = [f.name for f in PendingInventoryEmail._meta.get_fields()]
        existing_email = None
        
        if 'message_id' in model_fields:
            existing_email = PendingInventoryEmail.plain_objects.filter(message_id=message_id).first()
        
        if not existing_email:
            # Also fallback to subject check if needed, but allow new dates
            existing_email = PendingInventoryEmail.plain_objects.filter(subject=subject, sender_email=sender_email).last()
        
        if existing_email:
            # Only skip if it has data AND was approved
            has_requirements = BuyerRequirement.plain_objects.filter(source_email=existing_email).exists()
            has_pending_items = PendingInventoryItem.objects.filter(email=existing_email).exists()
            
            if (has_requirements or has_pending_items) and existing_email.status != 'pending' and existing_email.message_id == message_id:
                continue
        
        pending_email = existing_email
        if not pending_email:
            # Create new email record
            body = get_email_body(msg)
            attachments_info = handle_attachments(msg)
            full_text = body + "\n" + attachments_info
            
            # (routing logic continues...)
        else:
            body = pending_email.body_text
            attachments_info = "" # Assuming we don't re-process attachments if already in DB

        full_text = body + "\n" + attachments_info

        extracted_items = extract_inventory_items(full_text)
        if not extracted_items:
            continue

        # Intelligent Company Matching
        if tenant:
            matched_company = Company.objects.filter(tenant=tenant, email=sender_email).first()
        else:
            # Global lookup across all tenants
            matched_company = Company.plain_objects.filter(email=sender_email).first()
            if matched_company:
                tenant = matched_company.tenant

        if not matched_company:
            domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ''
            
            # Domain match only for non-generic providers
            if domain and domain not in ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com', 'icloud.com']:
                matched_company = Company.objects.filter(tenant=tenant, email__icontains=domain).first()
                if not matched_company:
                    # Try matching by contact email
                    from django.contrib.auth import get_user_model
                    ContactUser = get_user_model()
                    contact = ContactUser.objects.filter(tenant=tenant, email=sender_email, company__isnull=False).first()
                    if contact:
                        matched_company = contact.company

        # Fallback: Matching by sender name (least reliable)
        if not matched_company and sender_name:
            s_name = str(sender_name).strip()
            if len(s_name) > 3:
                matched_company = Company.objects.filter(tenant=tenant, name__icontains=s_name[:15]).first()

        # Assign Owner: Priority 1 = Company Creator, Priority 2 = Requesting User
        fetched_by = matched_company.created_by if matched_company and matched_company.created_by else request_user

        if not tenant:
            # Fallback to default tenant if still not found
            from apps.accounts.models import Tenant
            tenant = Tenant.objects.filter(name__icontains='Default').first() or Tenant.objects.first()

        pending_email = PendingInventoryEmail.objects.create(
            tenant=tenant,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body_text=body,
            message_id=message_id,
            received_at=timezone.now(),
            matched_company=matched_company,
            raw_extraction=extracted_items,
            fetched_by=fetched_by,
        )

        for item_data in extracted_items:
            intent = item_data.get('intent', 'supply')
            
            if intent == 'demand':
                # AUTOMATED: Create Buyer Requirement directly from email
                
                # Deduplication Check: Don't create if already exists for this email
                if BuyerRequirement.objects.filter(tenant=tenant, source_email=pending_email, material_name=item_data.get('product_name')).exists():
                    logger.info(f"Skipping duplicate Requirement for {item_data.get('product_name')}")
                    continue

                buyer = matched_company
                if not buyer:
                    buyer, _ = Company.objects.get_or_create(
                        tenant=tenant,
                        name=f"Email Lead: {sender_email}",
                        defaults={'is_active': False, 'description': 'Auto-created from requirement email'}
                    )

                BuyerRequirement.objects.create(
                    tenant=tenant,
                    buyer=buyer,
                    source='email',
                    source_email=pending_email,
                    material_name=item_data.get('product_name', 'Unknown'),
                    material_type=item_data.get('material_type', ''),
                    quantity_needed=item_data.get('quantity', 0.0),
                    unit=item_data.get('unit', 'lbs'),
                    max_price=item_data.get('price'),
                    notes=f"Auto-ingested from email: {subject}"
                )
                # Mark email as approved/processed immediately for Demand
                pending_email.status = 'approved'
                pending_email.processed_at = timezone.now()
                pending_email.save()
                logger.info(f"Automated: Created Buyer Requirement for {item_data.get('product_name')}")
            else:
                # Default: Pending Inventory Item (Supply) for approval
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
