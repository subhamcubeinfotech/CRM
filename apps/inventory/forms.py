from django import forms
from .models import Warehouse, InventoryItem, Material

class MaterialForm(forms.ModelForm):
    company = forms.ModelChoiceField(queryset=None, required=False, widget=forms.HiddenInput())
    # Field to pass the current company from the main form to the AJAX creation
    company_id_context = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import Company
        self.fields['company'].queryset = Company.objects.all()

    class Meta:
        model = Material
        fields = ['name', 'material_type', 'product_type', 'description', 'image', 'document', 'company']
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
            'name': forms.TextInput(attrs={'class': 'form-control border-light-subtle rounded-3', 'placeholder': 'Name for this location'}),
            'address': forms.TextInput(attrs={'class': 'form-control border-light-subtle rounded-3', 'placeholder': 'Start typing to search for a business or address'}),
            'city': forms.TextInput(attrs={'class': 'form-control border-light-subtle rounded-3'}),
            'state': forms.TextInput(attrs={'class': 'form-control border-light-subtle rounded-3'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control border-light-subtle rounded-3'}),
            'phone': forms.TextInput(attrs={'class': 'form-control border-light-subtle rounded-3', 'placeholder': '(000) 000-0000'}),
            'shipping_requirements': forms.Textarea(attrs={'class': 'form-control border-light-subtle rounded-3', 'rows': 2, 'placeholder': 'Insert Scales, Packing list, etc.'}),
            'delivery_appointment_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'pickup_appointment_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'is_remit_to': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make these optional for quick-add (handled by view parsing)
        self.fields['city'].required = False
        self.fields['state'].required = False
        self.fields['postal_code'].required = False
        
        # Remove empty choice but don't set initial (user wants no blue by default)
        self.fields['delivery_appointment_type'].choices = [('fcfs', 'FCFS'), ('required', 'Required')]
        self.fields['pickup_appointment_type'].choices = [('fcfs', 'FCFS'), ('required', 'Required')]




class InventoryItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Populate material choices - Filter by company if possible
        materials_qs = Material.objects.all().order_by('name')
        
        # Determine company for initial filtering
        item_company = None
        if self.instance and self.instance.pk:
            item_company = self.instance.company
        elif 'initial' in kwargs and 'company' in kwargs['initial']:
            item_company = kwargs['initial']['company']
            
        if item_company:
            materials_qs = materials_qs.filter(company=item_company)
        else:
            materials_qs = materials_qs.none()
            
        materials = list(materials_qs)
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
                if getattr(user, 'is_admin', False):
                    self.fields['company'].queryset = Company.objects.all()
                else:
                    from django.db.models import Q
                    self.fields['company'].queryset = Company.objects.filter(Q(created_by=user) | Q(pk=user_company.pk))
                
                self.fields['company'].initial = user_company
                self.fields['company'].disabled = False

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

        # Filter tags to exclude strictly numeric ones in the dropdown (clean up UI)
        from apps.orders.models import Tag
        from django.db.models import Q
        tenant_q = Q(tenant=user.tenant) if user and user.tenant else Q(tenant__isnull=True)
        tag_qs = Tag.objects.filter(tenant_q).exclude(name__regex=r'^\d+$')
        self.fields['tags'].queryset = tag_qs.order_by('name')

    class Meta:
        model = InventoryItem
        fields = [
            'sku', 'product_name', 'description', 'warehouse',
            'offered_weight', 'offered_weight_unit',
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
            'offered_weight': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Original Weight'}),
            'offered_weight_unit': forms.Select(choices=[('lbs', 'lbs'), ('kg', 'kg'), ('mt', 'MT')], attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Current Stock'}),
            'unit_of_measure': forms.Select(choices=[('lbs', 'lbs'), ('kg', 'kg'), ('mt', 'MT')], attrs={'class': 'form-select'}),
            'lot_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Insert a number'}),
            'po_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Insert a number'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'shipping_terms': forms.Select(attrs={'class': 'form-select'}),
            'representative': forms.Select(attrs={'class': 'form-select'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select select2-basic', 'id': 'tags-select-inventory'}),
            'pieces': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Pieces'}),
            'is_palletized': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'unit_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0001', 'placeholder': 'Price'}),
            'price_unit': forms.Select(choices=[('per lbs', 'per lbs'), ('per kg', 'per kg'), ('per mt', 'per MT')], attrs={'class': 'form-select'}),
        }
