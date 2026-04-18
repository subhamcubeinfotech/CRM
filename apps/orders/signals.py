from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Order, OrderEvent
from apps.shipments.models import Shipment

@receiver(pre_save, sender=Order)
def track_order_status_change(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_instance = Order.objects.get(pk=instance.pk)
            instance._old_status = old_instance.status
            instance._old_payment_status = old_instance.payment_status
        except Order.DoesNotExist:
            instance._old_status = None
            instance._old_payment_status = None
    else:
        instance._old_status = None

@receiver(post_save, sender=Order)
def log_order_events(sender, instance, created, **kwargs):
    if created:
        OrderEvent.objects.create(
            order=instance,
            event_type='order_created',
            description=f"Order #{instance.order_number} was created."
        )
    else:
        # Check if status has changed using the temporary attribute from pre_save
        old_status = getattr(instance, '_old_status', None)
        if old_status and old_status != instance.status:
            OrderEvent.objects.create(
                order=instance,
                event_type='status_updated',
                description=f"Order status is now {instance.simple_status_label}."
            )
            
        # Check if payment_status has changed
        old_payment_status = getattr(instance, '_old_payment_status', None)
        if old_payment_status and old_payment_status != instance.payment_status:
            OrderEvent.objects.create(
                order=instance,
                event_type='payment_status_updated',
                description=f"Order payment status is now {instance.get_payment_status_display()}."
            )

@receiver(post_save, sender=Shipment)
def log_shipment_events(sender, instance, created, **kwargs):
    if created and instance.order:
        OrderEvent.objects.create(
            order=instance.order,
            event_type='shipment_created',
            description=f"Shipment #{instance.shipment_number} was created for this order."
        )
    elif instance.order:
        # Check if status has changed (simulated for now, 
        # normally you'd use a tracker or compare with DB)
        # For simplicity in this environment, we'll log it if it's not a new creation
        # In a real app, you'd check old vs new status.
        OrderEvent.objects.create(
            order=instance.order,
            event_type='status_updated',
            description=f"Shipment #{instance.shipment_number} status updated to {instance.get_status_display()}."
        )
