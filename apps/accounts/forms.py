import re
from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from .models import Company

class CompanyForm(forms.ModelForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}))

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Company
        fields = [
            'name', 'company_type', 'tax_id',
            'phone', 'email', 'website',
            'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country',
            'payment_terms', 'credit_limit', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Name'}),
            'company_type': forms.Select(attrs={'class': 'form-select'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tax ID / EIN'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Website URL'}),
            'address_line1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address Line 1'}),
            'address_line2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address Line 2'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State / Province'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Zip / Postal Code'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country'}),
            'payment_terms': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Days (e.g., 30)'}),
            'credit_limit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Credit Limit'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
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
        if credit_limit is not None and credit_limit < 0:
            raise ValidationError("Credit limit cannot be negative.")
        return credit_limit

    def clean_payment_terms(self):
        payment_terms = self.cleaned_data.get('payment_terms')
        if payment_terms is not None and payment_terms < 0:
            raise ValidationError("Payment terms cannot be negative.")
        return payment_terms

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
