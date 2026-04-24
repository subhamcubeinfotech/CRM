from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import logout, get_user_model
from django.views import View
from django.utils import timezone
from datetime import timedelta
from .forms import SignupStep1Form, SignupStep2Form
from .models_tenant import Tenant
from .models_subscription import Subscription
from .models import SignupOTP
from .utils import generate_otp, send_otp_email
import logging

logger = logging.getLogger('apps.accounts')

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

@require_POST
def ajax_send_otp(request):
    """AJAX endpoint to send OTP"""
    email = request.POST.get('email', '').strip()
    
    # 1. Basic validation
    if not email:
        return JsonResponse({'success': False, 'message': 'Email is required.'})
    
    try:
        validate_email(email)
    except DjangoValidationError:
        return JsonResponse({'success': False, 'message': 'Invalid email format.'})

    # 2. Check if user already exists
    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse({'success': False, 'message': 'A user with this email already exists.'})

    # 3. Generate and send OTP
    otp_code = generate_otp()
    SignupOTP.objects.create(
        email=email,
        otp=otp_code,
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    
    if send_otp_email(email, otp_code):
        return JsonResponse({'success': True, 'message': f'Verification code sent to {email}.'})
    else:
        return JsonResponse({'success': False, 'message': 'Failed to send email. Please try again later.'})

@require_POST
def ajax_verify_otp(request):
    """AJAX endpoint to verify OTP"""
    email = request.POST.get('email', '').strip()
    otp_code = request.POST.get('otp', '').strip()
    
    if not email or not otp_code:
        return JsonResponse({'success': False, 'message': 'Email and OTP are required.'})

    otp_obj = SignupOTP.objects.filter(email=email, otp=otp_code).last()
    
    if otp_obj and not otp_obj.is_expired():
        otp_obj.is_verified = True
        otp_obj.save()
        
        # Store verification status in session
        request.session['otp_verified_email'] = email
        request.session.modified = True
        
        return JsonResponse({'success': True, 'message': 'Email verified successfully!'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid or expired OTP.'})

class SignupView(View):
    template_step1 = 'registration/signup_step1.html'
    template_step2 = 'registration/signup_step2.html'

    def get(self, request):
        # Capture plan from URL if present and store in session
        if 'plan' in request.GET:
            request.session['selected_plan'] = request.GET.get('plan')

        if 'back' in request.GET:
            if 'signup_step1_data' in request.session:
                del request.session['signup_step1_data']
            return redirect('signup')

        if 'signup_step1_data' in request.session:
            form = SignupStep2Form()
            return render(request, self.template_step2, {'form': form})
        else:
            initial_data = {}
            if 'selected_plan' in request.session:
                initial_data['plan'] = request.session['selected_plan']
            form = SignupStep1Form(initial=initial_data)
            return render(request, self.template_step1, {'form': form})

    def post(self, request):
        # Determine which step we are on based on session data
        if 'signup_step1_data' not in request.session:
            # Process Step 1
            form = SignupStep1Form(request.POST)
            if form.is_valid():
                email = form.cleaned_data.get('email')
                verified_email = request.session.get('otp_verified_email')
                
                if not verified_email or verified_email.lower() != email.lower():
                    form.add_error('email', "Please verify your email address with the OTP first.")
                    return render(request, self.template_step1, {'form': form})

                # Store plan selection from form in session
                request.session['selected_plan'] = form.cleaned_data.get('plan')
                
                request.session['signup_step1_data'] = form.cleaned_data
                form2 = SignupStep2Form()
                return render(request, self.template_step2, {'form': form2})
            return render(request, self.template_step1, {'form': form})
        else:
            # Process Step 2
            # Handle potential 'back' action
            if 'back' in request.POST:
                del request.session['signup_step1_data']
                return redirect('signup')
                
            form = SignupStep2Form(request.POST)
            if form.is_valid():
                step1_data = request.session.pop('signup_step1_data')
                selected_plan = request.session.pop('selected_plan', 'starter')
                
                # 1. Create a new Tenant (Inactive until payment)
                company_name = form.cleaned_data.get('name')
                tenant = Tenant.objects.create(
                    name=f"{company_name} Tenant",
                    is_active=False
                )
                
                # 2. Create the Company
                company = form.save(commit=False)
                company.tenant = tenant
                company.save()
                
                # 3. Create the User (Inactive until payment)
                user_form = SignupStep1Form(step1_data)
                user = user_form.save(commit=False)
                user.set_password(step1_data['password'])
                user.tenant = tenant
                user.company = company
                user.role = 'tenant_admin'
                user.is_active = False  # Deactivated until Stripe payment
                user.save()
                
                # 4. Create Initial Subscription Record
                Subscription.objects.create(
                    tenant=tenant,
                    plan=selected_plan if selected_plan in ['starter', 'professional'] else 'starter',
                    status='trialing',
                    is_active=False
                )
                
                # 5. Success message and Redirect to Stripe Checkout with selected plan
                logger.info(f"Signup Step 2 completed: User {user.email}. Redirecting to Stripe for plan: {selected_plan}")
                checkout_url = reverse('accounts:signup_checkout', kwargs={'tenant_id': tenant.id})
                return redirect(f"{checkout_url}?plan={selected_plan}")
                
            return render(request, self.template_step2, {'form': form})
