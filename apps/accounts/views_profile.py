from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages


@login_required
def profile_view(request):
    """View and edit user profile"""
    if request.method == 'POST':
        user = request.user
        
        # Update user fields
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        user.phone = request.POST.get('phone', '')
        
        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
            
        user.save()
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('accounts:profile')
        
    context = {
        'user': request.user,
    }
    return render(request, 'accounts/profile.html', context)


from .forms import TenantLogoForm

@login_required
def settings_view(request):
    """View and edit user and organization settings"""
    tenant = request.user.tenant
    
    # Fallback for superusers who might not be linked to a tenant
    if not tenant and request.user.is_superuser:
        from .models_tenant import Tenant
        tenant = Tenant.objects.first()
        
    subscription = getattr(tenant, 'subscription', None) if tenant else None
    
    if request.method == 'POST' and 'update_logo' in request.POST:
        if not request.user.is_admin:
            messages.error(request, "You don't have permission to change organization settings.")
            return redirect('accounts:settings')
            
        if not tenant:
            messages.error(request, "No organization found to update.")
            return redirect('accounts:settings')

        form = TenantLogoForm(request.POST, request.FILES, instance=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Organization logo updated successfully.')
            return redirect('accounts:settings')
    else:
        form = TenantLogoForm(instance=tenant) if tenant else None
        
    context = {
        'user': request.user,
        'tenant': tenant,
        'subscription': subscription,
        'logo_form': form,
    }
    return render(request, 'accounts/settings.html', context)
