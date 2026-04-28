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
from django.db.models import Q

from .enhancements import analyze_email_sentiment

logger = logging.getLogger('apps.ai_assistant')


def connect_imap(mailbox_user=None):
    """Connect to IMAP using a user's mailbox config, or fall back to shared .env settings."""
    if mailbox_user and getattr(mailbox_user, 'has_personal_mailbox_config', False):
        host = mailbox_user.imap_host or 'imap.gmail.com'
        port = int(mailbox_user.imap_port or 993)
        username = mailbox_user.imap_username or mailbox_user.effective_inbox_email
        password = mailbox_user.imap_password or ''
        use_ssl = bool(mailbox_user.imap_use_ssl)
    else:
        host = getattr(settings, 'IMAP_HOST', 'imap.gmail.com')
        port = int(getattr(settings, 'IMAP_PORT', 993))
        username = getattr(settings, 'EMAIL_HOST_USER', '')
        password = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
        use_ssl = bool(getattr(settings, 'IMAP_USE_SSL', True))

    if not username or not password:
        raise ValueError(
            "Email credentials not configured. Add personal IMAP details or shared EMAIL_HOST_USER/EMAIL_HOST_PASSWORD."
        )

    if use_ssl:
        mail = imaplib.IMAP4_SSL(host, port)
    else:
        mail = imaplib.IMAP4(host, port)
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
    Uses Anthropic Claude LLM to extract inventory items from unstructured email text.
    Handles multiple items, different units, and cleans up common email garbage.
    """
    from openai import OpenAI
    
    api_key = getattr(settings, 'KIMI_API_KEY', '').strip()
    if not api_key:
        logger.warning("Kimi API key missing. Skipping LLM extraction.")
        return []

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.moonshot.ai/v1",
    )
    
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
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": "You extract structured inventory data from business emails. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=2048,
        )
        content = response.choices[0].message.content
        # Extract JSON if Kimi adds conversational filler
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        data = json.loads(content)
        return data.get('items', [])
    except Exception as e:
        logger.error(f"Kimi Extraction failed: {e}. Falling back to Regex extraction.")
        return extract_items_regex_fallback(body_text)

def clean_product_name(name):
    """Deep clean of captured material names to remove boilerplate and noise."""
    if not name: return ""
    
    # 1. Strip lead-in boilerplate
    noise_prefixes = [
        r"^we\s+have\s+", r"^currently\s+in\s+stock\s+", r"^available\s+(?:at|in|on)\s+", 
        r"^inventory\s+of\s+", r"^requirement\s+for\s+", r"^looking\s+for\s+", r"^hi,?\s+",
        r"^new\s+inventory(?:\s+test)?\s+", r"^i\s+have\s+"
    ]
    name = name.strip()
    for pattern in noise_prefixes:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
    
    # 2. Strip trailing noise
    noise_suffixes = [
        r"\s+and$", r"\s+available$", r"\s+at\s+our\s+.*$", r"\s+with$", r"\s+for$"
    ]
    for pattern in noise_suffixes:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
        
    # 3. Final polish
    name = name.strip(' ,.-:*_')
    
    # Capitalize first letter of every word for professional look
    return ' '.join(word.capitalize() for word in name.split()) if name else ""

def extract_items_regex_fallback(body_text):
    """Robust regex extraction for logistics data using multi-pass patterns"""
    items = []
    
    # 1. Cleaner: Focus on the actual content
    clean_text = body_text.replace('*', '').replace('_', '')
    
    # Identify intent
    is_demand = any(re.search(rf"\b{word}\b", clean_text.lower()) for word in ['require', 'requirement', 'looking for', 'need', 'buy', 'want', 'purchasing'])
    
    # 2. Specialized Patterns
    patterns = [
        # Pattern A: [Quantity] [Unit] [Product Name] - Stops at punctuation or "and"
        # Example: "4500 lbs of Aluminum Siding"
        r"([\d,.]+)\s*(?:lbs?|tons?|kg|mt)?\s*(lbs?|tons?|kg|mt)\s+(?:of\s+)?(.*?)(?=\s+and\s+|\s+[\d,.]+\s*(?:lbs?|tons?|kg|mt)|[.,\n!]|$)",
        
        # Pattern B: [Product Name] [Quantity] [Unit]
        # Example: "Aluminum Siding 4500 lbs"
        # Limited look-behind to 40 characters to prevent catching whole sentences
        r"([^.\n!?,:]{3,40})\s+([\d,.]+)\s*(lbs?|tons?|kg|mt)",
        
        # Pattern C: Price detection (Price at end of line or after @/at)
        # Example: "... Aluminum at $0.90/lb"
        r"(.*?)\s+(?:at|@)\s+\$?\s*([\d,.]+)\s*/?\s*(lb|kg|ton|mt|lbs)?"
    ]
    
    # Pass 1: Primary extraction
    for i, p in enumerate(patterns[:2]): # Only look at A and B first
        for m in re.finditer(p, clean_text, re.IGNORECASE):
            if i == 0: # Pattern A
                qty_str, unit, prod = m.group(1), m.group(2), m.group(3)
            else: # Pattern B
                prod, qty_str, unit = m.group(1), m.group(2), m.group(3)
            
            prod = clean_product_name(prod)
            if not prod or len(prod) < 3: continue
            
            # Validation: Filter out common noise
            blacklist = ['regards', 'team', 'warehouse', 'any buyers', 'subject', 'fwd', 'date', 'april', 'may', 'june', 'july', 'best regards', 'thanks']
            if any(noise in prod.lower() for noise in blacklist):
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
                "price": None,
                "price_unit": f"per {unit}" if unit else "per lb"
            })

    # Pass 2: Price matching enrichment
    # Look for $X.XX/lb patterns and try to attach to the last item
    price_pattern = r"\$?\s*([\d,.]+)\s*/\s*(lb|kg|ton|mt|lbs?)"
    prices_found = re.findall(price_pattern, clean_text, re.IGNORECASE)
    if prices_found and items:
        # If there's only one price mentioned, it usually applies to all or the last mentioned item
        last_price, last_p_unit = prices_found[-1]
        try:
            items[-1]['price'] = float(last_price)
            items[-1]['price_unit'] = f"per {last_p_unit}"
        except: pass

    # 3. Deduplicate
    seen = set()
    unique_items = []
    for itm in items:
        key = (itm['product_name'].lower()[:20], itm['quantity'])
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


def fetch_and_process_emails(tenant, max_emails=10, request_user=None, mailbox_user=None):
    """
    Main entry point: connect to IMAP, fetch new emails, extract inventory items.
    """
    from .models import PendingInventoryEmail, PendingInventoryItem, BuyerRequirement
    from apps.accounts.models import Company

    try:
        mail = connect_imap(mailbox_user=mailbox_user)
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

            # Extract Recipient to route to specific user
            recipient_raw = msg.get('To', '')
            recipient_name, recipient_email = email.utils.parseaddr(recipient_raw)
            recipient_email = recipient_email.lower()

            # SPAM FILTER: Skip common junk domains
            junk_domains = ['jeevansathi.com', 'shaadi.com', 'linkedin.com', 'facebook.com', 'instagram.com', 'noreply', 'notifications']
            if any(junk in sender_email for junk in junk_domains):
                continue
        
        except Exception as e:
            logger.error(f"Error fetching email {eid}: {e}")
            continue
            
        model_fields = [f.name for f in PendingInventoryEmail._meta.get_fields()]
        body = get_email_body(msg)
        attachments_info = handle_attachments(msg)

        full_text = body + "\n" + attachments_info

        extracted_items = extract_inventory_items(full_text)
        if not extracted_items:
            continue

        # ─── ROUTING LOGIC ───
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        resolved_tenant = tenant or getattr(mailbox_user, 'tenant', None)
        fetched_by = mailbox_user or request_user
        mailbox_owner = mailbox_user
        
        # 1. Route by Recipient (To: address) - Primary Priority
        target_user = User.objects.filter(
            Q(email__iexact=recipient_email) | Q(inbox_email__iexact=recipient_email)
        ).select_related('tenant').first() if recipient_email else None
        if target_user:
            fetched_by = target_user
            mailbox_owner = target_user
            resolved_tenant = getattr(target_user, 'tenant', None)
            logger.info(f"Routed email to user: {target_user.email} based on To header")
        elif mailbox_user:
            recipient_email = recipient_email or mailbox_user.effective_inbox_email

        # 2. Intelligent Company Matching (Fallback)
        matched_company = Company.objects.filter(email=sender_email).first()
        if not matched_company:
            domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ''
            if domain and domain not in ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com', 'icloud.com']:
                matched_company = Company.objects.filter(email__icontains=domain).first()

        # Update tenant if matched globally and not already set by Recipient
        if not resolved_tenant and matched_company and matched_company.tenant:
            resolved_tenant = matched_company.tenant
            fetched_by = matched_company.created_by if matched_company.created_by else request_user

        if not resolved_tenant:
            # Fallback to default tenant if still not found
            from apps.accounts.models import Tenant
            resolved_tenant = Tenant.objects.filter(name__icontains='Default').first() or Tenant.objects.first()

        if mailbox_owner and not recipient_email:
            recipient_email = mailbox_owner.effective_inbox_email

        if mailbox_owner and not resolved_tenant:
            resolved_tenant = getattr(mailbox_owner, 'tenant', None)

        duplicate_qs = PendingInventoryEmail.plain_objects.all()
        if mailbox_owner:
            duplicate_qs = duplicate_qs.filter(mailbox_user=mailbox_owner)
        elif recipient_email:
            duplicate_qs = duplicate_qs.filter(recipient_email__iexact=recipient_email)
        elif resolved_tenant:
            duplicate_qs = duplicate_qs.filter(tenant=resolved_tenant)

        existing_email = None
        if 'message_id' in model_fields and message_id:
            existing_email = duplicate_qs.filter(message_id=message_id).first()

        if not existing_email:
            existing_email = duplicate_qs.filter(
                subject=subject,
                sender_email=sender_email,
                recipient_email__iexact=recipient_email or '',
                body_text=body,
            ).last()

        pending_email = None
        if existing_email:
            has_requirements = BuyerRequirement.plain_objects.filter(source_email=existing_email).exists()
            has_pending_items = PendingInventoryItem.objects.filter(email=existing_email).exists()

            if existing_email.status == 'rejected' and (has_requirements or has_pending_items):
                sentiment_data = analyze_email_sentiment(subject, body)
                existing_email.tenant = resolved_tenant
                existing_email.sender_email = sender_email
                existing_email.sender_name = sender_name
                existing_email.recipient_email = recipient_email
                existing_email.subject = subject
                existing_email.body_text = body
                existing_email.message_id = message_id
                existing_email.received_at = timezone.now()
                existing_email.status = 'pending'
                existing_email.matched_company = matched_company
                existing_email.raw_extraction = extracted_items
                existing_email.sentiment_label = sentiment_data.get('sentiment_label', 'neutral')
                existing_email.sentiment_score = sentiment_data.get('sentiment_score', 0.0)
                existing_email.priority_level = sentiment_data.get('priority_level', 'medium')
                existing_email.sentiment_reason = sentiment_data.get('sentiment_reason', '')
                existing_email.processed_at = None
                existing_email.processed_by = None
                existing_email.fetched_by = fetched_by
                existing_email.mailbox_user = mailbox_owner
                existing_email.save()
                existing_email.items.all().delete()
                BuyerRequirement.plain_objects.filter(source_email=existing_email).delete()
                pending_email = existing_email
            elif has_requirements or has_pending_items:
                continue

        sentiment_data = analyze_email_sentiment(subject, body)

        if not pending_email:
            pending_email = PendingInventoryEmail.objects.create(
                tenant=resolved_tenant,
                sender_email=sender_email,
                sender_name=sender_name,
                recipient_email=recipient_email,
                subject=subject,
                body_text=body,
                message_id=message_id,
                received_at=timezone.now(),
                matched_company=matched_company,
                raw_extraction=extracted_items,
                sentiment_label=sentiment_data.get('sentiment_label', 'neutral'),
                sentiment_score=sentiment_data.get('sentiment_score', 0.0),
                priority_level=sentiment_data.get('priority_level', 'medium'),
                sentiment_reason=sentiment_data.get('sentiment_reason', ''),
                fetched_by=fetched_by,
                mailbox_user=mailbox_owner,
            )

        for item_data in extracted_items:
            intent = item_data.get('intent', 'supply')
            
            if intent == 'demand':
                # AUTOMATED: Create Buyer Requirement directly from email
                
                # Deduplication Check: Don't create if already exists for this email
                if BuyerRequirement.objects.filter(tenant=resolved_tenant, source_email=pending_email, material_name=item_data.get('product_name')).exists():
                    logger.info(f"Skipping duplicate Requirement for {item_data.get('product_name')}")
                    continue

                buyer = matched_company
                if not buyer:
                    buyer, _ = Company.objects.get_or_create(
                        tenant=resolved_tenant,
                        name=f"Email Lead: {sender_email}",
                        defaults={'is_active': False, 'description': 'Auto-created from requirement email'}
                    )

                BuyerRequirement.objects.create(
                    tenant=resolved_tenant,
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
