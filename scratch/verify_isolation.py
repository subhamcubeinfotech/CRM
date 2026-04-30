import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.append(os.getcwd())
django.setup()

from apps.accounts.models import Company
from apps.inventory.models import Material

def get_company_materials(company_id):
    try:
        company = Company.objects.get(id=company_id)
        print(f"\n>>> Checking Company: {company.name} (ID: {company.id})")
        
        # Exact logic from views.py
        materials = company.material_tags.all().order_by('name')
        owned_materials = Material.objects.filter(company=company).order_by('name')
        if owned_materials.exists():
            materials = (materials | owned_materials).distinct()
            
        print(f"Count: {materials.count()}")
        for m in materials:
            print(f"  - {m.name} (ID: {m.id}, Owned by Company ID: {m.company_id})")
    except Company.DoesNotExist:
        print(f"Company {company_id} not found.")

# Test multiple companies
test_ids = [60, 1, 17, 5]
for cid in test_ids:
    get_company_materials(cid)
