import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.ai_assistant.email_ingestion import fetch_and_process_emails

logger = logging.getLogger('apps.ai_assistant')

class Command(BaseCommand):
    help = 'Check the configured vendor inbox for new inventory emails'

    def handle(self, *args, **options):
        # Using the DEFAULT_TENANT or fallback
        tenant = getattr(settings, 'DEFAULT_TENANT', None)
        
        self.stdout.write(self.style.SUCCESS(f'Checking inbox...'))
        
        try:
            processed = fetch_and_process_emails(tenant)
            self.stdout.write(self.style.SUCCESS(f'Successfully processed {processed} emails.'))
        except Exception as e:
            logger.error(f'Inbox check failed: {e}')
            self.stderr.write(self.style.ERROR(f'Inbox check failed: {e}'))
