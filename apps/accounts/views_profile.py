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


@login_required
def settings_view(request):
    """View and edit user settings"""
    context = {
        'user': request.user,
    }
    return render(request, 'accounts/settings.html', context)
