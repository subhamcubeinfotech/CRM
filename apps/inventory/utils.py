import logging
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger('apps.inventory')

def send_low_stock_alert(item):
    """
    Sends an email alert when an item's quantity falls below its reorder level.
    """
    if not item.representative or not item.representative.email:
        logger.warning(f"No representative email found for item {item.sku}. Skipping alert.")
        return False

    subject = f"LOW STOCK ALERT: {item.product_name} ({item.sku})"
    
    context = {
        'item': item,
        'current_stock': item.quantity,
        'reorder_level': item.reorder_level,
        'unit': item.unit_of_measure,
        'warehouse': item.warehouse.name if item.warehouse else "N/A",
    }
    
    # Simple text message
    message = f"""
Hello {item.representative.get_full_name() or item.representative.username},

This is an automated alert from FreightPro. The following item has fallen below its reorder level:

Material: {item.product_name}
SKU: {item.sku}
Current Stock: {item.quantity} {item.unit_of_measure}
Reorder Level: {item.reorder_level} {item.unit_of_measure}
Warehouse: {item.warehouse.name if item.warehouse else "N/A"}

Please take necessary action to replenish the stock.

Thanks,
FreightPro Inventory System
"""
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [item.representative.email],
            fail_silently=False,
        )
        logger.info(f"Low stock alert sent to {item.representative.email} for {item.sku}")
        return True
    except Exception as e:
        logger.error(f"Failed to send low stock alert for {item.sku}: {str(e)}")
        return False
