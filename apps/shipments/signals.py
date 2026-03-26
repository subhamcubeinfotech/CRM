from django.db.models.signals import post_save, post_init
from django.dispatch import receiver
from .models import Shipment, ShipmentHistory

@receiver(post_init, sender=Shipment)
def store_initial_shipment_data(sender, instance, **kwargs):
    """Store initial values to detect changes in post_save"""
    if instance.pk:
        instance._initial_status = instance.status
        instance._initial_carrier_id = instance.carrier_id
        instance._initial_pickup_contact = instance.pickup_contact
        instance._initial_delivery_contact = instance.delivery_contact

@receiver(post_save, sender=Shipment)
def log_shipment_audit_events(sender, instance, created, **kwargs):
    """Log audit events when critical fields change"""
    if created:
        ShipmentHistory.objects.create(
            shipment=instance,
            action="Created this Shipment",
            description=f"Shipment #{instance.shipment_number} was created in the system.",
            icon="fas fa-plus-circle",
            user=getattr(instance, '_current_user', instance.created_by)
        )
        return

    # Check for changes
    history_entries = []
    
    # 1. Status Change
    old_status = getattr(instance, '_initial_status', None)
    if old_status and old_status != instance.status:
        history_entries.append(ShipmentHistory(
            shipment=instance,
            action=f"Changed Status to {instance.get_status_display()}",
            description=f"Status updated from {dict(Shipment.STATUS_CHOICES).get(old_status)}",
            icon="fas fa-sync-alt",
            user=getattr(instance, '_current_user', None)
        ))

    # 2. Carrier Change
    old_carrier_id = getattr(instance, '_initial_carrier_id', None)
    if old_carrier_id != instance.carrier_id:
        from apps.accounts.models import Company
        old_carrier_name = Company.objects.get(pk=old_carrier_id).name if old_carrier_id else "None"
        new_carrier_name = instance.carrier.name if instance.carrier else "None"
        history_entries.append(ShipmentHistory(
            shipment=instance,
            action=f"Changed Freight Carrier",
            description=f"From {old_carrier_name} to {new_carrier_name}",
            icon="fas fa-truck",
            user=getattr(instance, '_current_user', None)
        ))

    # 3. Pickup Contact Change
    old_pickup = getattr(instance, '_initial_pickup_contact', None)
    if old_pickup != instance.pickup_contact:
        history_entries.append(ShipmentHistory(
            shipment=instance,
            action=f"Changed Pickup Contact to {instance.pickup_contact or 'None'}",
            description=f"Previously: {old_pickup or 'None'}",
            icon="fas fa-user-edit",
            user=getattr(instance, '_current_user', None)
        ))

    # 4. Delivery Contact Change
    old_delivery = getattr(instance, '_initial_delivery_contact', None)
    if old_delivery != instance.delivery_contact:
        history_entries.append(ShipmentHistory(
            shipment=instance,
            action=f"Changed Delivery Contact to {instance.delivery_contact or 'None'}",
            description=f"Previously: {old_delivery or 'None'}",
            icon="fas fa-user-edit",
            user=getattr(instance, '_current_user', None)
        ))

    if history_entries:
        ShipmentHistory.objects.bulk_create(history_entries)
        
    # Update initial values for subsequent saves in the same request if any
    instance._initial_status = instance.status
    instance._initial_carrier_id = instance.carrier_id
    instance._initial_pickup_contact = instance.pickup_contact
    instance._initial_delivery_contact = instance.delivery_contact
