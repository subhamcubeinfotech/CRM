from django.core.management.base import BaseCommand
from apps.ai_assistant.email_ingestion import fetch_and_process_emails
from apps.accounts.models import Tenant

class Command(BaseCommand):
    help = 'Fetches new vendor emails via IMAP for a specific tenant'

    def add_arguments(self, parser):
        parser.add_argument('--tenant_id', type=int, help='Specific tenant ID to process')

    def handle(self, *args, **options):
        tenant_id = options.get('tenant_id')
        
        if tenant_id:
            try:
                tenant = Tenant.objects.get(id=tenant_id)
                tenants = [tenant]
            except Tenant.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'Tenant {tenant_id} not found'))
                return
        else:
            # Default to all tenants or just the first one for testing
            tenants = Tenant.objects.all()

        for tenant in tenants:
            self.stdout.write(f'Fetching emails for tenant: {tenant.name} (ID: {tenant.id})...')
            processed = fetch_and_process_emails(tenant)
            self.stdout.write(self.style.SUCCESS(f'Successfully processed {processed} emails for {tenant.name}'))
