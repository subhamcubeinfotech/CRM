from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import login
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
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
        'invite_form': TeamInviteForm(tenant=request.user.tenant, user=request.user),
    }
    return render(request, 'accounts/team_list.html', context)

@login_required
def invite_team_member(request):
    """View to handle sending a new team invitation"""
    if not request.user.tenant:
        messages.error(request, "Your account is not associated with any Company/Tenant. Only Company Admins can invite team members.")
        return redirect('accounts:team_list')

    # Check plan-based user limit
    subscription = getattr(request.user.tenant, 'subscription', None)
    if subscription and not subscription.can_add_user():
        limits = subscription.get_limits()
        messages.error(
            request, 
            f"You have reached the maximum of {limits['max_users']} users on the {subscription.get_plan_display()} plan. "
            f"Please upgrade to Professional plan for unlimited users."
        )
        return redirect('accounts:team_list')

    if request.method == 'POST':
        form = TeamInviteForm(request.POST, tenant=request.user.tenant, user=request.user)
        if form.is_valid():
            invitation = form.save(commit=False)
            invitation.tenant = request.user.tenant
            invitation.invited_by = request.user
            invitation.save()
            
            # Send invitation email
            try:
                accept_url = request.build_absolute_uri(
                    reverse('accounts:accept_invitation', kwargs={'token': invitation.token})
                )
                inviter_name = request.user.get_full_name() or request.user.username
                tenant_name = request.user.tenant.name
                
                subject = f"You're invited to join {tenant_name} on FreightPro"
                message = (
                    f"Hi {invitation.first_name or 'there'},\n\n"
                    f"{inviter_name} has invited you to join {tenant_name} on FreightPro as a {invitation.get_role_display()}.\n\n"
                    f"Click the link below to set up your account:\n"
                    f"{accept_url}\n\n"
                    f"This invitation link is unique to you. Do not share it with anyone.\n\n"
                    f"Best regards,\n"
                    f"FreightPro Team"
                )
                
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[invitation.email],
                    fail_silently=False,
                )
            except Exception as e:
                import logging
                logger = logging.getLogger('apps.accounts')
                logger.error(f"Failed to send invitation email to {invitation.email}: {str(e)}")
            
            messages.success(request, f"Invitation sent successfully to {invitation.email}!")
            return redirect('accounts:team_list')
    else:
        form = TeamInviteForm(tenant=request.user.tenant, user=request.user)
    
    return render(request, 'accounts/team_invite.html', {'form': form})

def accept_invitation(request, token):
    """Public view for invited users to set up their account"""
    invitation = get_object_or_404(TeamInvitation, token=token, is_accepted=False)
    
    # Log out any currently logged-in user so form doesn't get pre-filled
    if request.user.is_authenticated:
        from django.contrib.auth import logout as auth_logout
        auth_logout(request)
    
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
            
            # Log the new user in
            login(request, user)
            messages.success(request, f"Welcome to the team, {user.first_name}!")
            return redirect('dashboard')
    else:
        # Pre-fill only first/last name from invitation, leave username & password empty
        form = InvitationAcceptanceForm(initial={
            'first_name': invitation.first_name or '',
            'last_name': invitation.last_name or '',
        })
    
    return render(request, 'accounts/accept_invitation.html', {
        'form': form,
        'invitation': invitation
    })
