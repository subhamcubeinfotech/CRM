from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Order, OrderEvent
from apps.shipments.models import Shipment

@receiver(post_save, sender=Order)
def log_order_events(sender, instance, created, **kwargs):
    if created:
        OrderEvent.objects.create(
            order=instance,
            event_type='order_created',
            description=f"Order #{instance.order_number} was created."
        )
    else:
        # Simple check for status update vs other field updates
        # In a full app, you'd use a __init__ tracker, but here we can 
        # log it as a general update or generic status log.
        OrderEvent.objects.create(
            order=instance,
            event_type='status_updated',
            description=f"Order status is now {instance.get_status_display()}."
        )

@receiver(post_save, sender=Shipment)
def log_shipment_events(sender, instance, created, **kwargs):
    if created:
        OrderEvent.objects.create(
            order=instance.order,
            event_type='shipment_created',
            description=f"Shipment #{instance.shipment_number} was created for this order."
        )
    else:
        # Check if status has changed (simulated for now, 
        # normally you'd use a tracker or compare with DB)
        # For simplicity in this environment, we'll log it if it's not a new creation
        # In a real app, you'd check old vs new status.
        OrderEvent.objects.create(
            order=instance.order,
            event_type='status_updated',
            description=f"Shipment #{instance.shipment_number} status updated to {instance.get_status_display()}."
        )
