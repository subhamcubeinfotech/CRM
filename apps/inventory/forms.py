from django import forms
from .models import Warehouse, InventoryItem, Material

class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ['name', 'material_type', 'product_type', 'description', 'image', 'document']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Custom display name for this material'}),
            'material_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. PE, PP'}),
            'product_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Film, Flake'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional description of this material'}),
            'image': forms.FileInput(attrs={'class': 'd-none', 'id': 'materialImageInput'}),
            'document': forms.FileInput(attrs={'class': 'd-none', 'id': 'materialDocumentInput'}),
        }

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            'name', 'address', 'city', 'state', 'postal_code', 'phone', 
            'shipping_requirements', 'delivery_appointment_type', 
            'pickup_appointment_type', 'is_remit_to'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Name for this location'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Start typing to search for a business or address'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(000) 000-0000'}),
            'shipping_requirements': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Insert Scales, Packing list, etc.'}),
            'delivery_appointment_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'pickup_appointment_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'is_remit_to': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class InventoryItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Populate material choices
        materials = Material.objects.all().order_by('name')
        self.fields['product_name'].widget = forms.Select(
            choices=[('', 'Select a material')] + [(m.name, m.name) for m in materials],
            attrs={'class': 'form-select'}
        )

        # Aggressive company locking
        if user:
            from apps.accounts.models import Company
            user_company = user.company
            if not user_company and user.tenant:
                user_company = Company.objects.filter(tenant=user.tenant).first()
            
            if user_company:
                self.fields['company'].queryset = Company.objects.filter(id=user_company.id)
                self.fields['company'].initial = user_company
                self.fields['company'].disabled = True

            # Representative locking
            self.fields['representative'].queryset = user.__class__.objects.filter(id=user.id)
            self.fields['representative'].initial = user
            self.fields['representative'].disabled = True

        # Dynamic packaging choices from orders module
        try:
            from apps.orders.models import PackagingType
            p_types = PackagingType.objects.all().order_by('name')
            self.fields['packaging'].widget = forms.Select(
                choices=[('', 'Select packaging type')] + [(p.name, p.name) for p in p_types],
                attrs={'class': 'form-select'}
            )
        except (ImportError, Exception):
            # Fallback if PackagingType is not available
            pass

    class Meta:
        model = InventoryItem
        fields = [
            'sku', 'product_name', 'description', 'warehouse', 'location',
            'quantity', 'unit_of_measure', 'lot_number', 'po_number',
            'company', 'shipping_terms', 'representative', 'tags',
            'packaging', 'pieces', 'is_palletized',
            'unit_cost', 'price_unit'
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
            'pieces': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Pieces'}),
            'is_palletized': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'unit_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0001', 'placeholder': 'Price'}),
            'price_unit': forms.Select(choices=[('per lbs', 'per lbs'), ('per kg', 'per kg'), ('per MT', 'per MT'), ('per unit', 'per unit')], attrs={'class': 'form-select'}),
        }
