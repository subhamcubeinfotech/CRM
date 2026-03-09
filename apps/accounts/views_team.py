from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import CustomUser

@login_required
def team_list(request):
    """List all team members in the current tenant"""
    if not request.user.role == 'admin':
        messages.error(request, "Only tenant administrators can manage the team.")
        return redirect('dashboard')
        
    team_members = CustomUser.objects.filter(tenant=request.user.tenant)
    
    context = {
        'team_members': team_members,
    }
    return render(request, 'accounts/team_list.html', context)
