from apps.inventory.models import InventoryItem, InventoryTransaction
from apps.ai_assistant.models import PendingInventoryEmail, SmartMatch, BuyerRequirement
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from apps.accounts.models import Company, Tenant

try:
    # Target Tenant 17
    tenant = Tenant.objects.get(id=17)
    from apps.accounts.models import CustomUser
    user = CustomUser.objects.filter(tenant=tenant).first()
    
    # Target Item in Tenant 17
    item = InventoryItem.objects.filter(tenant=tenant, sku='EML-92939-3').first()
    if not item:
        item = InventoryItem.objects.filter(tenant=tenant).first()
        
    if item:
        print(f"Seeding for Item: {item.product_name} (SKU: {item.sku})")
        # Create Transactions for Forecasting (SHIP)
        # Note: auto_now_add=True in model means we can't backdate easily via .create()
        # but the calculation looks for transactions in the window. 
        for i in range(5):
            InventoryTransaction.objects.create(
                item=item, 
                tenant=tenant, 
                transaction_type='SHIP', 
                quantity_change=Decimal('-1500'), 
                new_quantity=item.quantity - (1500*(i+1)), 
                user=user,
                notes=f"Test shipment {i+1}"
            )
        print("Seeded Forecasting data.")

    # Create Email for Sentiment Analysis
    PendingInventoryEmail.objects.create(
        tenant=tenant, 
        sender_email='angry_supplier@example.com', 
        sender_name='Angry Supplier', 
        subject='URGENT: DISAPPOINTED with delay', 
        body_text='I am very disappointed with the delay in processing our last batch in Deloitte warehouse. We need an ASAP response.', 
        received_at=timezone.now(), 
        status='pending', 
        fetched_by=user
    )
    print("Seeded Sentiment data.")

    # Create Match for Quote Drafting
    buyer = Company.objects.filter(tenant=tenant).exclude(id=item.company_id).first() if item else None
    if buyer and item:
        req = BuyerRequirement.objects.create(
            tenant=tenant, 
            buyer=buyer, 
            material_name=item.product_name, 
            quantity_needed=5000, 
            unit='lbs'
        )
        SmartMatch.objects.create(
            tenant=tenant, 
            requirement=req, 
            inventory_item=item, 
            confidence_score=95, 
            match_reason='High fidelity match for your Deloitte inventory.'
        )
        print("Seeded Smart Match data.")

except Exception as e:
    import traceback
    print(f"Error seeding: {e}")
    traceback.print_exc()
