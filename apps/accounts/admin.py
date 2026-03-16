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
