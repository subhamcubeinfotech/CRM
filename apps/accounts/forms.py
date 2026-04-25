import re
from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import Company

class TagInputField(forms.MultipleChoiceField):
    """Custom field to allow any value typed in Select2 tags, bypassing choice validation."""
    def valid_value(self, value):
        return True

class CompanyForm(forms.ModelForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}))
    
    services_provided = TagInputField(
        choices=[],
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select select2-tags',
            'multiple': 'multiple',
            'data-placeholder': 'Type a service and press Enter...'
        }),
        label="Services Provided"
    )

    material_tags = TagInputField(
        choices=[],
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select select2-tags',
            'multiple': 'multiple',
            'data-placeholder': 'Type and press Enter to add...'
        }),
        label="Materials"
    )

    company_tags = TagInputField(
        choices=[],
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select select2-tags',
            'multiple': 'multiple',
            'data-placeholder': 'Type and press Enter to add...'
        }),
        label="Company Tags"
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Add labels to make them look like the screenshot
        self.fields['legal_name'].label = "Legal Name"

        # If editing, populate the choices with EXISTING linked items only

        # If editing, populate the choices with EXISTING linked items only
        # so they show up as tags in the searchable box
        if self.instance and self.instance.pk:
            # For JSON field (Services)
            if self.instance.services_provided:
                self.fields['services_provided'].initial = self.instance.services_provided
                self.fields['services_provided'].widget.choices = [(s, s) for s in self.instance.services_provided]
            
            # For M2M (Materials)
            linked_materials = self.instance.material_tags.all()
            if linked_materials:
                self.fields['material_tags'].initial = [m.pk for m in linked_materials]
                # Provide IDs as choices so Select2 can map them
                self.fields['material_tags'].widget.choices = [(m.pk, m.name) for m in linked_materials]
            
            # For M2M (Tags)
            linked_tags = self.instance.company_tags.all()
            if linked_tags:
                self.fields['company_tags'].initial = [t.pk for t in linked_tags]
                self.fields['company_tags'].widget.choices = [(t.pk, t.name) for t in linked_tags]

        # Make financial fields optional for now so they don't block save
        self.fields['payment_terms'].required = False
        self.fields['credit_limit'].required = False

    class Meta:
        model = Company
        fields = [
            'name', 'legal_name', 'company_type', 'tax_id',
            'phone', 'email', 'website',
            'description', 'logo',
            'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country',
            'payment_terms', 'credit_limit', 'crm_status', 'last_touch', 'next_touch', 'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Name'}),
            'company_type': forms.Select(attrs={'class': 'form-select'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tax ID / EIN'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Website URL'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Brief description of this company', 'rows': 4}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'address_line1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address Line 1'}),
            'address_line2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address Line 2'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State / Province'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Zip / Postal Code'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country'}),
            'payment_terms': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Days (e.g., 30)'}),
            'credit_limit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Credit Limit'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'legal_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Legal Name'}),
            'crm_status': forms.Select(attrs={'class': 'form-select'}),
            'last_touch': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'next_touch': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            if not re.match(r'^[\d\+\-\(\)\s]+$', phone):
                raise ValidationError("Phone number can only contain numbers, spaces, and the characters +, -, (, ).")
            
            digit_count = sum(c.isdigit() for c in phone)
            if digit_count < 10:
                raise ValidationError("Phone number must contain at least 10 digits.")
        return phone

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email):
                raise ValidationError("Please enter a valid email address (e.g., user@example.com).")
        return email

    def clean_postal_code(self):
        postal_code = self.cleaned_data.get('postal_code')
        if postal_code:
            if not re.match(r'^[\w\s\-]+$', postal_code):
                raise ValidationError("Postal code can only contain letters, numbers, spaces, and dashes.")
            if len(postal_code.strip()) < 3:
                raise ValidationError("Postal code must be at least 3 characters long.")
        return postal_code

    def clean_credit_limit(self):
        credit_limit = self.cleaned_data.get('credit_limit')
        if credit_limit is None:
            return 0
        if credit_limit < 0:
            raise ValidationError("Credit limit cannot be negative.")
        return credit_limit

    def clean_payment_terms(self):
        payment_terms = self.cleaned_data.get('payment_terms')
        if payment_terms is None:
            return 30
        if payment_terms < 0:
            raise ValidationError("Payment terms cannot be negative.")
        return payment_terms

    def clean_services_provided(self):
        services = self.cleaned_data.get('services_provided')
        if not services and 'services_provided' in self.data:
            services = self.data.getlist('services_provided')
        
        if isinstance(services, str):
            return [s.strip() for s in services.split(',') if s.strip()]
        return services or []

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            name = name.strip()
            if len(name) < 2:
                raise ValidationError("Company name must be at least 2 characters long.")
            
            # Check for duplicates in the same tenant
            queryset = Company.objects.filter(name__iexact=name)
            
            # If editing, exclude current instance
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            # If we have a user/tenant context, ensure we check within that
            # Note: TenantManager should handle filtering if current_tenant is set,
            # but being explicit is safer if the middleware isn't active in this context.
            if queryset.exists():
                raise ValidationError(f"A company with the name '{name}' already exists.")
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Manually capture services_provided since it's a JSONField and 
        # not in Meta.fields to avoid standard field handling issues
        services = self.cleaned_data.get('services_provided')
        if not services and 'services_provided' in self.data:
            services = self.data.getlist('services_provided')
        
        if services is not None:
            if isinstance(services, str):
                instance.services_provided = [s.strip() for s in services.split(',') if s.strip()]
            else:
                instance.services_provided = services

        if commit:
            instance.save()
            self.process_m2m_data()
        return instance

    def save_m2m(self):
        """Ensure custom materials/tags processing runs for commit=False save flows."""
        self.process_m2m_data()

    def process_m2m_data(self):
        """Custom method to handle auto-creation of Tags and Materials."""
        instance = self.instance
        
        # 0. Set Tenant if missing (critical for Material creation)
        if not instance.tenant:
            if hasattr(self, 'user') and self.user and hasattr(self.user, 'tenant'):
                instance.tenant = self.user.tenant
            elif 'request' in self.data and hasattr(self.data['request'], 'user'):
                 instance.tenant = self.data['request'].user.tenant

        # 1. Handle Materials (ManyToMany)
        # Be extremely aggressive in capturing the data
        material_data = self.cleaned_data.get('material_tags')
        if not material_data:
            material_data = self.data.getlist('material_tags')
        
        # Normalize to list of strings
        if isinstance(material_data, str):
            material_data = [v.strip() for v in material_data.split(',') if v.strip()]
        elif isinstance(material_data, list) and len(material_data) == 1 and ',' in str(material_data[0]):
            material_data = [v.strip() for v in material_data[0].split(',') if v.strip()]
        
        material_objs = []
        if material_data:
            from apps.inventory.models import Material
            for item in material_data:
                item_str = str(item).strip() if item else ""
                if not item_str: continue
                try:
                    if item_str.isdigit():
                        mat = Material.objects.get(pk=int(item_str))
                    else:
                        mat, created = Material.objects.get_or_create(
                            tenant=instance.tenant,
                            name=item_str
                        )
                    material_objs.append(mat)
                except:
                    pass
            
            instance.material_tags.set(material_objs)
        else:
            instance.material_tags.clear()
        
        # 2. Handle Tags (ManyToMany)
        tag_data = self.cleaned_data.get('company_tags') or self.data.getlist('company_tags')
        if tag_data:
            from apps.orders.models import Tag
            tag_objs = []
            for item in tag_data:
                item_str = str(item).strip()
                if not item_str: continue
                try:
                    if item_str.isdigit():
                        tag_objs.append(Tag.objects.get(pk=int(item_str)))
                    else:
                        tag, _ = Tag.objects.get_or_create(tenant=instance.tenant, name=item_str)
                        tag_objs.append(tag)
                except Exception as e:
                    print(f"Error saving tag '{item}': {e}")
            
            instance.company_tags.set(tag_objs)
        else:
            instance.company_tags.clear()

class CustomPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = self.cleaned_data.get('email')
        UserModel = get_user_model()
        if not UserModel.objects.filter(email__iexact=email, is_active=True).exists():
            raise ValidationError("There is no active user associated with this email address.")
        return email

class SignupStep1Form(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}))
    plan = forms.ChoiceField(
        choices=[('starter', 'Starter ($100/mo)'), ('pro', 'Professional ($299/mo)')],
        initial='starter',
        widget=forms.Select(attrs={'class': 'form-select mb-3'}),
        label="Choose Your Plan"
    )
    
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'username', 'email', 'password']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name', 'required': True}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name', 'required': True}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username', 'required': True}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Work Email', 'required': True}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        UserModel = get_user_model()
        if UserModel.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        UserModel = get_user_model()
        if UserModel.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            try:
                validate_password(password, self.instance)
            except ValidationError as e:
                raise ValidationError(e)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data

class SignupStep2Form(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            'name', 'address_line1', 'address_line2', 'city', 'state', 
            'postal_code', 'country', 'tax_id', 'phone'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Name', 'required': True}),
            'address_line1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address Line 1', 'required': True}),
            'address_line2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address Line 2 (Optional)'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City', 'required': True}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State / Province', 'required': True}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Zip / Postal Code', 'required': True}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country', 'required': True, 'value': 'USA'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tax ID / Business Registration Number'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number', 'required': True}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            name = name.strip()
            if Company.objects.filter(name__iexact=name).exists():
                raise ValidationError(f"A company with the name '{name}' already exists.")
        return name

    # Reusing some clean methods from CompanyForm
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            if not re.match(r'^[\d\+\-\(\)\s]+$', phone):
                raise ValidationError("Phone number can only contain numbers, spaces, and the characters +, -, (, ).")
            digit_count = sum(c.isdigit() for c in phone)
            if digit_count < 10:
                raise ValidationError("Phone number must contain at least 10 digits.")
        return phone

    def clean_postal_code(self):
        postal_code = self.cleaned_data.get('postal_code')
        if postal_code:
            if not re.match(r'^[\w\s\-]+$', postal_code):
                raise ValidationError("Postal code can only contain letters, numbers, spaces, and dashes.")
            if len(postal_code.strip()) < 3:
                raise ValidationError("Postal code must be at least 3 characters long.")
        return postal_code
