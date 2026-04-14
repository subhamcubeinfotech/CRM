
def process_recurring_invoices():
    """
    Checks all active recurring templates and generates invoices if due.
    Can be run as a cron job or celery periodic task.
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import Invoice, RecurringInvoice, InvoiceLineItem, InvoiceLineItem
    import calendar

    def add_months(sourcedate, months):
        month = sourcedate.month - 1 + months
        year = sourcedate.year + month // 12
        month = month % 12 + 1
        day = min(sourcedate.day, calendar.monthrange(year, month)[1])
        return sourcedate.replace(year=year, month=month, day=day)

    today = timezone.now().date()
    templates = RecurringInvoice.objects.filter(is_active=True, next_generation_date__lte=today)
    
    count = 0
    for template in templates:
        # Create new invoice
        invoice = Invoice.objects.create(
            customer=template.customer,
            invoice_date=today,
            tax_rate=template.tax_rate,
            terms=template.terms,
            payment_instructions=template.payment_instructions,
            created_by=template.created_by,
            tenant=template.tenant,
            status='draft' # Start as draft for approval workflow
        )
        
        # Copy line items
        for item in template.line_items.all():
            InvoiceLineItem.objects.create(
                invoice=invoice,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
        
        # Update template state
        template.last_generated = today
        
        # Calculate next date
        if template.frequency == 'weekly':
            template.next_generation_date += timedelta(days=7)
        elif template.frequency == 'biweekly':
            template.next_generation_date += timedelta(days=14)
        elif template.frequency == 'monthly':
            template.next_generation_date = add_months(template.next_generation_date, 1)
        elif template.frequency == 'quarterly':
            template.next_generation_date = add_months(template.next_generation_date, 3)
        elif template.frequency == 'yearly':
            template.next_generation_date = add_months(template.next_generation_date, 12)
            
        template.save()
        count += 1
        
    return count
