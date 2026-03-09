import time
# Stub for Celery PDF tasks
# from celery import shared_task

# @shared_task
def generate_invoice_pdf(invoice_id):
    """Generates PDF for a given invoice_id and saves to Document model."""
    print(f"Generating PDF for Invoice ID: {invoice_id}")
    time.sleep(1) # simulate work
    return f"generated_invoice_{invoice_id}.pdf"

# @shared_task
def generate_bol_pdf(shipment_id):
    """Generates BOL PDF for a given shipment_id and saves to Document model."""
    print(f"Generating BOL for Shipment ID: {shipment_id}")
    time.sleep(1) # simulate work
    return f"generated_bol_{shipment_id}.pdf"
