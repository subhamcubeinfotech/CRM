from apps.inventory.models import Material
from django.db.models import Count

duplicates = Material.plain_objects.values('name').annotate(name_count=Count('id')).filter(name_count__gt=1)

print("Duplicate Materials Found:")
for dup in duplicates:
    name = dup['name']
    records = Material.plain_objects.filter(name=name)
    print(f"\nName: {name}")
    for r in records:
        print(f"  ID: {r.id}, Tenant: {r.tenant}, Created: {r.created_at}")
