"""
Management command: check_inbox
Fetches unread emails from the configured inbox and extracts inventory data.
Usage: python manage.py check_inbox
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Check inbox for supplier emails and extract inventory data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-emails',
            type=int,
            default=10,
            help='Maximum number of emails to process (default: 10)',
        )
        parser.add_argument(
            '--run-matching',
            action='store_true',
            help='Also run smart matching after email ingestion',
        )

    def handle(self, *args, **options):
        from apps.accounts.models import Tenant
        from apps.ai_assistant.email_ingestion import fetch_and_process_emails
        from apps.ai_assistant.matching import run_matching

        max_emails = options['max_emails']

        # Process for each tenant
        for tenant in Tenant.objects.all():
            self.stdout.write(f"\n📧 Processing emails for tenant: {tenant.name}")

            try:
                count = fetch_and_process_emails(tenant, max_emails=max_emails)
                if count > 0:
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Processed {count} emails"))
                else:
                    self.stdout.write("  📭 No new inventory emails found")
            except ValueError as e:
                self.stdout.write(self.style.WARNING(f"  ⚠️ {str(e)}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error: {str(e)}"))

            if options['run_matching']:
                self.stdout.write("  🧠 Running smart matching...")
                try:
                    matches = run_matching(tenant)
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Created {matches} new matches"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ❌ Matching error: {str(e)}"))

        self.stdout.write(self.style.SUCCESS("\n✅ Done!"))
