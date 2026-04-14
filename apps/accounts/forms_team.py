from django import forms
from django.core.exceptions import ValidationError
from .models import TeamInvitation, CustomUser

class TeamInviteForm(forms.ModelForm):
    """Form to send a team invitation"""
    class Meta:
        model = TeamInvitation
        fields = ['email', 'role']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Member Work Email'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email already exists in the system.")
        
        # Check for existing pending invitation in this tenant
        if self.tenant:
            if TeamInvitation.objects.filter(email__iexact=email, tenant=self.tenant, is_accepted=False).exists():
                raise ValidationError("A pending invitation already exists for this email in your team.")
                
        return email


class InvitationAcceptanceForm(forms.ModelForm):
    """Form for invited users to set up their account"""
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}))

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'username', 'password']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Choose a Username'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")
        
        # Add basic password strength check
        if password and len(password) < 6:
            self.add_error('password', "Password must be at least 6 characters.")

        return cleaned_data
