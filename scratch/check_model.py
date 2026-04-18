import os
import sys
import django

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.ai_assistant.models import PendingInventoryEmail

print("Fields in PendingInventoryEmail:")
for field in PendingInventoryEmail._meta.get_fields():
    print(f"- {field.name}")
