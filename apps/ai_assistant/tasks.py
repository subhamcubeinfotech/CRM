from __future__ import absolute_import, unicode_literals
import logging
from celery import shared_task
from django.conf import settings
from .email_ingestion import fetch_and_process_emails

logger = logging.getLogger('apps.ai_assistant')

@shared_task(name='apps.ai_assistant.tasks.fetch_vendor_emails')
def fetch_vendor_emails():
    """Celery task that processes new vendor emails for all active tenants."""
    from apps.accounts.models import Tenant
    
    tenants = Tenant.objects.filter(is_active=True)
    if not tenants.exists():
        logger.warning('No active tenants found for email ingestion; skipping.')
        return 0
        
    total_processed = 0
    for tenant in tenants:
        try:
            processed = fetch_and_process_emails(tenant)
            total_processed += processed
            logger.info(f'Tenant {tenant.name} processed {processed} emails.')
        except Exception as e:
            logger.error(f'Error processing emails for tenant {tenant.name}: {e}')
            
    return total_processed
