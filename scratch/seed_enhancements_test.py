from apps.inventory.models import InventoryItem, InventoryTransaction
from apps.ai_assistant.models import PendingInventoryEmail, SmartMatch, BuyerRequirement
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from apps.accounts.models import Company

try:
    item = InventoryItem.objects.get(id=144)
    tenant = item.tenant
    # Try to find a user in this tenant
    from apps.accounts.models import CustomUser
    user = item.representative or CustomUser.objects.filter(tenant=tenant).first()
    
    # Create Transactions for Forecasting
    for i in range(5):
        InventoryTransaction.objects.create(
            item=item, 
            tenant=tenant, 
            transaction_type='SHIP', 
            quantity_change=Decimal('-1500'), 
            new_quantity=item.quantity - (1500*(i+1)), 
            user=user, 
            timestamp=timezone.now() - timedelta(days=i*2)
        )
    print("Seeded Forecasting data.")

    # Create Email for Sentiment Analysis
    email = PendingInventoryEmail.objects.create(
        tenant=tenant, 
        sender_email='angry_supplier@example.com', 
        sender_name='Angry Supplier', 
        subject='URGENT: DISAPPOINTED with delay', 
        body_text='I am very disappointed with the delay in processing our last batch. We need an ASAP response or we will stop deliveries.', 
        received_at=timezone.now(), 
        status='pending', 
        fetched_by=user
    )
    print("Seeded Sentiment data.")

    # Create Match for Quote Drafting
    buyer = Company.objects.filter(tenant=tenant).exclude(id=item.company_id).first()
    if buyer:
        req = BuyerRequirement.objects.create(
            tenant=tenant, 
            buyer=buyer, 
            material_name='Iron Scraps', 
            quantity_needed=5000, 
            unit='lbs'
        )
        SmartMatch.objects.create(
            tenant=tenant, 
            requirement=req, 
            inventory_item=item, 
            confidence_score=95, 
            match_reason='Perfect material match with available stock.'
        )
        print("Seeded Smart Match data.")
    else:
        print("No buyer company found to create requirement.")

except Exception as e:
    print(f"Error seeding: {e}")
