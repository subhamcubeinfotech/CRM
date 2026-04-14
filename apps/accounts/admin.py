"""
Accounts Admin Configuration
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'company_type', 'city', 'country', 'phone', 'is_active']
    list_filter = ['company_type', 'is_active', 'country', 'created_at']
    search_fields = ['name', 'email', 'phone', 'tax_id']
    readonly_fields = ['created_at', 'updated_at']
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


from .models import LoginAuditLog

@admin.register(LoginAuditLog)
class LoginAuditLogAdmin(admin.ModelAdmin):
    """Read-only log view for security auditing"""
    list_display = ('username', 'ip_address', 'status', 'timestamp')
    list_filter = ('status', 'timestamp')
    search_fields = ('username', 'ip_address', 'user_agent')
    readonly_fields = ('username', 'ip_address', 'user_agent', 'status', 'timestamp')
    
    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False # Keeping it for security verification, but usually logs shouldn't be deleted easily
