import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import Tenant, CustomUser, Subscription, Company
from apps.inventory.models import Warehouse, InventoryItem
from apps.shipments.models import Shipment
from django.utils import timezone

def create_dummy_data():
    # Create Tenants
    tenant1, _ = Tenant.objects.get_or_create(name="Customer Alpha", domain="alpha.freightpro.com")
    tenant2, _ = Tenant.objects.get_or_create(name="Customer Beta", domain="beta.freightpro.com")
    
    # Create Subscriptions
    Subscription.objects.get_or_create(tenant=tenant1, plan='professional', status='active')
    Subscription.objects.get_or_create(tenant=tenant2, plan='basic', status='active')
    
    # Create Companies for Tenant 1
    c1, _ = Company.plain_objects.get_or_create(
        name="Tech Logistics", company_type='customer', tenant=tenant1,
        defaults={'email': 'info@techlog.com', 'city': 'San Jose'}
    )
    Company.plain_objects.get_or_create(
        name="FastTrack Carriers", company_type='carrier', tenant=tenant1,
        defaults={'email': 'dispatch@fasttrack.com'}
    )

    # Create Companies for Tenant 2
    c2, _ = Company.plain_objects.get_or_create(
        name="Global Retailers", company_type='customer', tenant=tenant2,
        defaults={'email': 'supply@globalretail.com'}
    )

    # Create Users for Tenant 1
    user1_admin, created = CustomUser.objects.get_or_create(
        username="alpha_admin",
        defaults={'email': "admin@alpha.com", 'role': 'admin', 'tenant': tenant1}
    )
    if created:
        user1_admin.set_password("password123")
        user1_admin.save()
        
    user1_staff, created = CustomUser.objects.get_or_create(
        username="alpha_staff",
        defaults={'email': "staff@alpha.com", 'role': 'warehouse', 'tenant': tenant1}
    )
    if created:
        user1_staff.set_password("password123")
        user1_staff.save()

    # Create Users for Tenant 2
    user2_admin, created = CustomUser.objects.get_or_create(
        username="beta_admin",
        defaults={'email': "admin@beta.com", 'role': 'admin', 'tenant': tenant2}
    )
    if created:
        user2_admin.set_password("password123")
        user2_admin.save()

    # Create Warehouses (Tenant Aware)
    w1, _ = Warehouse.plain_objects.get_or_create(
        name="Alpha Storage NYC", code="AL-NYC", tenant=tenant1,
        defaults={'address': "123 Alpha St", 'city': "New York", 'state': "NY", 'postal_code': "10001"}
    )
    w2, _ = Warehouse.plain_objects.get_or_create(
        name="Beta Warehouse LA", code="BT-LA", tenant=tenant2,
        defaults={'address': "456 Beta Ave", 'city': "Los Angeles", 'state': "CA", 'postal_code': "90001"}
    )
    
    # Create Inventory Items
    InventoryItem.plain_objects.get_or_create(
        sku="ITEM-A1", product_name="Widget Alpha", warehouse=w1, tenant=tenant1,
        defaults={'quantity': 100, 'unit_cost': 10.50}
    )
    InventoryItem.plain_objects.get_or_create(
        sku="ITEM-B1", product_name="Gadget Beta", warehouse=w2, tenant=tenant2,
        defaults={'quantity': 50, 'unit_cost': 25.00}
    )

    print("Dummy data created successfully!")
    print(f"Customer 1: alpha_admin / password123")
    print(f"Customer 2: beta_admin / password123")

if __name__ == "__main__":
    create_dummy_data()
