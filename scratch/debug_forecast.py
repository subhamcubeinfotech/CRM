from apps.inventory.models import InventoryItem, InventoryTransaction
from apps.accounts.models import CustomUser, Tenant

try:
    i = InventoryItem.objects.get(id=144)
    print(f"DEBUG: Item 144 ({i.product_name}) SKU: {i.sku}, Tenant ID: {i.tenant.id if i.tenant else 'None'}")
    
    tx_count = InventoryTransaction.objects.filter(item=i, transaction_type='SHIP').count()
    print(f"DEBUG: Transactions count for 144: {tx_count}")

    # Check who 'shubha' is (user in the screenshot)
    u = CustomUser.objects.filter(username__icontains='shubha').first()
    if u:
        print(f"DEBUG: User 'shubha' Tenant ID: {u.tenant.id if u.tenant else 'None'}")
        if u.tenant != i.tenant:
            print(f"WARNING: Tenant Mismatch! Item 144 is in tenant {i.tenant.id}, but user is in tenant {u.tenant.id}")
    else:
        print("DEBUG: User 'shubha' not found.")

except Exception as e:
    print(f"ERROR: {e}")
