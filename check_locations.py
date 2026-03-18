from apps.accounts.models import Company
from apps.inventory.models import Warehouse

def check_netsmartz():
    try:
        c = Company.objects.get(name__icontains='NETSMARTZ')
        print(f"Company: {c.name}")
        print(f"Address: {c.full_address}")
        
        warehouses = c.warehouses.filter(is_active=True)
        print(f"Active Warehouses: {warehouses.count()}")
        for wh in warehouses:
            print(f"- {wh.name} ({wh.code}): {wh.full_address}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_netsmartz()
