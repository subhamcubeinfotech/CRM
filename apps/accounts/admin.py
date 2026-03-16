"""
Accounts Admin Configuration
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib import messages
from .models import CustomUser, Company, SystemSetting, WholesaleRequest
from .models_tenant import Tenant
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.sites.shortcuts import get_current_site
from django.db import transaction
import logging

logger = logging.getLogger('apps.accounts')


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'company_type', 'city', 'country', 'phone', 'is_active']
    list_filter = ['company_type', 'is_active', 'country', 'created_at']
    search_fields = ['name', 'email', 'phone', 'tax_id']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['request_wholesale_account']

    @admin.action(description="Request Wholesale Account from Urban Poling")
    def request_wholesale_account(self, request, queryset):
        """
        Sends a formal request for a wholesale account to the configured recipient.
        Uses WHOLESALE_ONBOARDING_RECIPIENT from settings.
        """
        success_count = 0
        error_count = 0
        
        recipient_email = SystemSetting.get_val('wholesale_recipient', getattr(settings, 'WHOLESALE_ONBOARDING_RECIPIENT', 'subham@yopmail.com'))
        
        for company in queryset:
            try:
                context = {
                    'company': company,
                    'user': request.user,
                }
                html_message = render_to_string('emails/wholesale_account_request.html', context)
                subject = f"Wholesale Account Request: {company.name}"
                
                send_mail(
                    subject=subject,
                    message=f"Request for {company.name}. Please see HTML version.",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recipient_email],
                    html_message=html_message,
                    fail_silently=False,
                )
                success_count += 1
                logger.info(f"Wholesale request sent for {company.name} to {recipient_email} by admin {request.user}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error sending wholesale request for {company.name}: {str(e)}")
                self.message_user(request, f"Error for {company.name}: {str(e)}", messages.ERROR)
        
        if success_count:
            self.message_user(request, f"Successfully requested wholesale accounts for {success_count} companies.", messages.SUCCESS)
        if error_count:
            self.message_user(request, f"Failed to send {error_count} requests. Check logs.", messages.WARNING)
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'company_type', 'tax_id', 'is_active')
        }),
        ('Address', {
            'fields': ('address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country')
        }),
        ('Contact', {
            'fields': ('phone', 'email', 'website')
        }),
        ('Financial', {
            'fields': ('payment_terms', 'credit_limit')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'role', 'company', 'phone', 'is_verified', 'is_active']
    list_filter = ['role', 'is_verified', 'is_active', 'is_staff', 'created_at']
    search_fields = ['username', 'email', 'phone', 'company__name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email', 'phone', 'avatar')}),
        ('Role & Company', {'fields': ('role', 'company', 'is_verified')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important Dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role', 'company'),
        }),
    )

@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'description', 'updated_at']
    search_fields = ['key', 'value']


@admin.register(WholesaleRequest)
class WholesaleRequestAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'contact_name', 'desired_username', 'wholesaler_email', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['company_name', 'contact_name', 'wholesaler_email', 'desired_username']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['status']
    actions = ['approve_and_invite']

    @admin.action(description="Approve & Send Account Invitation")
    def approve_and_invite(self, request, queryset):
        success_count = 0
        already_processed = 0
        
        for req in queryset:
            if req.status != 'pending':
                already_processed += 1
                continue
                
            try:
                with transaction.atomic():
                    # Check if email already taken in User system
                    if CustomUser.objects.filter(email__iexact=req.wholesaler_email).exists():
                        raise Exception(f"User with email {req.wholesaler_email} already exists.")
                    
                    if CustomUser.objects.filter(username__iexact=req.desired_username).exists():
                        raise Exception(f"Username '{req.desired_username}' is already taken.")

                    # Extra safeguard: Re-validate username rules just in case it was edited in admin
                    username = req.desired_username
                    if not username or len(username) < 5 or len(username) > 15:
                        raise Exception(f"Username '{username}' must be 5-15 characters.")
                    if username[0].isdigit():
                        raise Exception(f"Username '{username}' cannot start with a number.")

                    # Check if Company already exists
                    if Company.objects.filter(name__iexact=req.company_name).exists():
                        raise Exception(f"Company '{req.company_name}' already exists in the system.")
                    if Company.objects.filter(email__iexact=req.wholesaler_email).exists():
                        raise Exception(f"Company email '{req.wholesaler_email}' is already associated with another company.")

                    # 1. Create Tenant
                    tenant = Tenant.objects.create(name=f"{req.company_name} Wholesale")
                
                    # 2. Create Company
                    company = Company.objects.create(
                        tenant=tenant,
                        name=req.company_name,
                        company_type='customer',
                        email=req.wholesaler_email,
                        address_line1=req.business_address,
                        is_active=True
                    )
                    
                    # 3. Create User
                    names = req.contact_name.split(' ', 1)
                    first_name = names[0]
                    last_name = names[1] if len(names) > 1 else ''
                    
                    user = CustomUser.objects.create(
                        username=req.desired_username,
                        email=req.wholesaler_email,
                        first_name=first_name,
                        last_name=last_name,
                        tenant=tenant,
                        company=company,
                        role='customer',
                        is_active=True,
                        is_verified=True
                    )
                    user.set_unusable_password()
                    user.save()
                    
                    # 4. Generate Token and Send Invitation Link
                    token = default_token_generator.make_token(user)
                    uid = urlsafe_base64_encode(force_bytes(user.pk))
                    domain = get_current_site(request).domain
                    protocol = 'https' if request.is_secure() else 'http'
                    
                    context = {
                        'contact_name': req.contact_name,
                        'company_name': req.company_name,
                        'username': req.desired_username,
                        'uid': uid,
                        'token': token,
                        'domain': domain,
                        'protocol': protocol,
                    }
                    
                    html_message = render_to_string('emails/wholesale_invitation.html', context)
                    send_mail(
                        subject="Invitation: Activate Your Urban Poling Wholesale Account",
                        message=f"Welcome! Please activate your account at {protocol}://{domain}",
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[req.wholesaler_email],
                        html_message=html_message,
                    )
                    
                    # 5. Update Request Status
                    req.status = 'approved'
                    req.save()
                    success_count += 1
                
            except Exception as e:
                self.message_user(request, f"Error processing {req.company_name}: {str(e)}", messages.ERROR)
                logger.error(f"Wholesale Approval Error for {req.company_name}: {str(e)}")

        if success_count:
            self.message_user(request, f"Successfully approved {success_count} requests and sent invitations.", messages.SUCCESS)
        if already_processed:
            self.message_user(request, f"{already_processed} requests were already processed and skipped.", messages.WARNING)
