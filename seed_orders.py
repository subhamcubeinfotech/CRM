import os
import django
import random
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.orders.models import Order, ManifestItem
from apps.accounts.models import Company, Tenant, CustomUser
from apps.inventory.models import Warehouse
from apps.shipments.models import Shipment

def seed_diverse_orders():
    tenants = Tenant.objects.all()
    if not tenants.exists():
        print("No tenants found. Run seed_multi_tenant.py first.")
        return

    materials = [
        ("PE (B Trims)", 0.095, 0.14),
        ("HDPE regrind", 0.35, 0.48),
        ("PP Bales", 0.12, 0.18),
        ("PET Bottles", 0.22, 0.31),
        ("Aluminum Scrap", 0.65, 0.82),
        ("Cardboard OCC", 0.05, 0.08),
    ]

    statuses = ['draft', 'confirmed', 'in_transit', 'delivered', 'closed']
    payment_statuses = ['pending', 'partial', 'paid', 'overdue']

    for tenant in tenants:
        users = CustomUser.objects.filter(tenant=tenant)
        suppliers = list(Company.objects.filter(tenant=tenant, company_type='vendor'))
        receivers = list(Company.objects.filter(tenant=tenant, company_type='customer'))
        warehouses = list(Warehouse.objects.filter(tenant=tenant))

        if not all([users.exists(), suppliers, receivers, warehouses]):
            # Create if missing
            if not suppliers:
                s, _ = Company.objects.get_or_create(tenant=tenant, name=f"Supplier {tenant.name}", company_type='vendor')
                suppliers = [s]
            if not receivers:
                r, _ = Company.objects.get_or_create(tenant=tenant, name=f"Receiver {tenant.name}", company_type='customer')
                receivers = [r]
            if not warehouses:
                w, _ = Warehouse.objects.get_or_create(tenant=tenant, name=f"Hub {tenant.name}")
                warehouses = [w]

        for user in users:
            print(f"Seeding 20 orders for {user.username} in {tenant.name}...")
            for i in range(20):
                mat_name, b_price, s_price = random.choice(materials)
                target_weight = Decimal(random.randint(40000, 250000))
                
                status = random.choice(statuses)
                pay_status = random.choice(payment_statuses)
                
                # Adjust status logic for realism
                if status == 'delivered':
                    pay_status = random.choice(['paid', 'pending', 'overdue'])
                if status == 'draft':
                    pay_status = 'pending'

                order = Order.objects.create(
                    tenant=tenant,
                    order_number=f"{tenant.name[:3].upper()}-O-{user.id}-{2000+i}",
                    po_number=f"PO-{random.randint(10000, 99999)}",
                    so_number=f"SO-{random.randint(1000, 9999)}",
                    supplier=random.choice(suppliers),
                    receiver=random.choice(receivers),
                    source_location=random.choice(warehouses),
                    destination_location=random.choice(warehouses),
                    total_weight_target=target_weight,
                    shipping_terms=random.choice(["FOB Destination", "EXW", "CIF"]),
                    representative=user,
                    created_by=user,
                    status=status,
                    payment_status=pay_status,
                    created_at=timezone.now() - timedelta(days=random.randint(0, 60))
                )

                # Add 1-3 manifest items
                num_items = random.randint(1, 3)
                for _ in range(num_items):
                    m_name, m_buy, m_sell = random.choice(materials)
                    # Split target weight among items
                    item_weight = target_weight / num_items
                    ManifestItem.objects.create(
                        order=order,
                        material=m_name,
                        weight=item_weight,
                        weight_unit="lbs",
                        buy_price=Decimal(str(m_buy + random.uniform(-0.02, 0.02))),
                        sell_price=Decimal(str(m_sell + random.uniform(-0.02, 0.02))),
                        packaging=random.choice(["Bales", "Boxes", "Pallets"])
                    )

                # Create 0-2 shipments for some orders to show progress
                if status in ['in_transit', 'delivered', 'confirmed']:
                    num_shipments = random.randint(1, 2)
                    for s_i in range(num_shipments):
                        # Each shipment takes ~30-50% of weight
                        ship_weight = (target_weight * Decimal(str(random.uniform(0.3, 0.5))))
                        Shipment.objects.create(
                            tenant=tenant,
                            order=order,
                            customer=order.receiver, # FIXED: customer is required
                            shipment_number=f"SHP-{order.order_number}-{s_i}",
                            total_weight=ship_weight,
                            status='in_transit' if status == 'in_transit' else 'delivered',
                            pickup_date=order.created_at + timedelta(days=random.randint(1, 5))
                        )

    print("Seeding complete!")

if __name__ == "__main__":
    seed_diverse_orders()
