from django import forms
from .models import Warehouse, InventoryItem

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            'name', 'code', 'address', 'city', 'state', 'country', 
            'postal_code', 'phone', 'email', 'company', 'manager', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = [
            'sku', 'product_name', 'description', 'warehouse', 'location',
            'quantity', 'unit_of_measure', 'lot_number', 'serial_number',
            'unit_cost', 'reorder_level'
        ]
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'form-control'}),
            'product_name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_of_measure': forms.TextInput(attrs={'class': 'form-control'}),
            'lot_number': forms.TextInput(attrs={'class': 'form-control'}),
            'serial_number': forms.TextInput(attrs={'class': 'form-control'}),
            'unit_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reorder_level': forms.NumberInput(attrs={'class': 'form-control'}),
        }
