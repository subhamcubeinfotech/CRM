from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import login
from .models import CustomUser, TeamInvitation
from .forms_team import TeamInviteForm, InvitationAcceptanceForm

@login_required
def team_list(request):
    """List all team members and pending invitations"""
    team_members = CustomUser.objects.filter(tenant=request.user.tenant)
    pending_invites = TeamInvitation.objects.filter(tenant=request.user.tenant, is_accepted=False)
    
    context = {
        'team_members': team_members,
        'pending_invites': pending_invites,
    }
    return render(request, 'accounts/team_list.html', context)

@login_required
def invite_team_member(request):
    """View to handle sending a new team invitation"""
    if not request.user.tenant:
        messages.error(request, "Your account is not associated with any Company/Tenant. Only Company Admins can invite team members.")
        return redirect('accounts:team_list')

    if request.method == 'POST':
        form = TeamInviteForm(request.POST, tenant=request.user.tenant)
        if form.is_valid():
            invitation = form.save(commit=False)
            invitation.tenant = request.user.tenant
            invitation.invited_by = request.user
            invitation.save()
            
            # Note: Email sending would happen here
            messages.success(request, f"Invitation sent successfully to {invitation.email}!")
            return redirect('accounts:team_list')
    else:
        form = TeamInviteForm(tenant=request.user.tenant)
    
    return render(request, 'accounts/team_invite.html', {'form': form})

def accept_invitation(request, token):
    """Public view for invited users to set up their account"""
    invitation = get_object_or_404(TeamInvitation, token=token, is_accepted=False)
    
    if request.method == 'POST':
        form = InvitationAcceptanceForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = invitation.email
            user.role = invitation.role
            user.tenant = invitation.tenant
            if invitation.invited_by.company:
                user.company = invitation.invited_by.company
            user.is_active = True
            user.is_verified = True
            user.set_password(form.cleaned_data['password'])
            user.save()
            
            # Mark invitation as accepted
            invitation.is_accepted = True
            invitation.save()
            
            # Log the user in
            login(request, user)
            messages.success(request, f"Welcome to the team, {user.first_name}!")
            return redirect('dashboard')
    else:
        form = InvitationAcceptanceForm()
    
    return render(request, 'accounts/accept_invitation.html', {
        'form': form,
        'invitation': invitation
    })
