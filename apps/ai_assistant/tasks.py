from __future__ import absolute_import, unicode_literals
import logging
from celery import shared_task
from django.conf import settings
from .email_ingestion import fetch_and_process_emails

logger = logging.getLogger('apps.ai_assistant')

@shared_task(name='apps.ai_assistant.tasks.fetch_vendor_emails')
def fetch_vendor_emails():
    """Celery task that processes new vendor emails for the current tenant.
    In a multi‑tenant setup you would loop over all active tenants; for now we
    assume a single tenant context (settings.DEFAULT_TENANT or similar).
    """
    # Simplify: use a dummy tenant placeholder – you can replace with actual
    # tenant logic later.
    tenant = getattr(settings, 'DEFAULT_TENANT', None)
    if tenant is None:
        logger.warning('No tenant configured for email ingestion; skipping.')
        return 0
    processed = fetch_and_process_emails(tenant)
    logger.info(f'Email ingestion task processed {processed} emails.')
    return processed
