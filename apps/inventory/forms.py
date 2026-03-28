from django import forms
from .models import Warehouse, InventoryItem

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            'name', 'code', 'address', 'city', 'state', 
            'postal_code', 'phone', 'email', 'is_active'
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
            'quantity', 'unit_of_measure', 'lot_number', 'po_number',
            'company', 'shipping_terms', 'representative', 'tags',
            'packaging', 'pieces', 'is_palletized',
            'unit_cost', 'price_unit', 'reorder_level'
        ]
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SKU / Part Number'}),
            'product_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Select a material'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Type a note'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Insert a location'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Weight'}),
            'unit_of_measure': forms.Select(choices=[('lbs', 'lbs'), ('kg', 'kg'), ('mt', 'MT'), ('pcs', 'pcs')], attrs={'class': 'form-select'}),
            'lot_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Insert a number'}),
            'po_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Insert a number'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'shipping_terms': forms.Select(attrs={'class': 'form-select'}),
            'representative': forms.Select(attrs={'class': 'form-select'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select select2-basic'}),
            'packaging': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Select packaging type'}),
            'pieces': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Pieces'}),
            'is_palletized': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'unit_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0001', 'placeholder': 'Price'}),
            'price_unit': forms.Select(choices=[('per lbs', 'per lbs'), ('per kg', 'per kg'), ('per MT', 'per MT'), ('per unit', 'per unit')], attrs={'class': 'form-select'}),
            'reorder_level': forms.NumberInput(attrs={'class': 'form-control'}),
        }
