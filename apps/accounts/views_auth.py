from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.views import View
from .forms import SignupStep1Form, SignupStep2Form
from .models_tenant import Tenant
from .models import SystemSetting
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
import logging

logger = logging.getLogger('apps.accounts')

class SignupView(View):
    template_step1 = 'registration/signup_step1.html'
    template_step2 = 'registration/signup_step2.html'

    def get(self, request):
        if 'signup_step1_data' in request.session:
            form = SignupStep2Form()
            return render(request, self.template_step2, {'form': form})
        else:
            form = SignupStep1Form()
            return render(request, self.template_step1, {'form': form})

    def post(self, request):
        # Determine which step we are on based on session data
        if 'signup_step1_data' not in request.session:
            # Process Step 1
            form = SignupStep1Form(request.POST)
            if form.is_valid():
                request.session['signup_step1_data'] = form.cleaned_data
                form2 = SignupStep2Form()
                return render(request, self.template_step2, {'form': form2})
            return render(request, self.template_step1, {'form': form})
        else:
            # Process Step 2
            # Handle potential 'back' action
            if 'back' in request.POST:
                del request.session['signup_step1_data']
                return redirect('accounts:signup')
                
            form = SignupStep2Form(request.POST)
            if form.is_valid():
                step1_data = request.session.pop('signup_step1_data')
                
                # 1. Create a new Tenant for the user (since FreightPro works with Tenants)
                company_name = form.cleaned_data.get('name')
                tenant = Tenant.objects.create(name=f"{company_name} Tenant")
                
                # 2. Create the Company
                company = form.save(commit=False)
                company.tenant = tenant
                company.save()
                
                # 3. Create the User
                user_form = SignupStep1Form(step1_data)
                user = user_form.save(commit=False)
                user.set_password(step1_data['password'])
                user.tenant = tenant
                user.company = company
                user.role = 'customer'  # Default role for new signups
                user.save()
                
                # 4. Success message and Redirect to Login
                logger.info(f"New signup completed: User {user.email} from Company {company.name}")
                messages.success(request, f"Registration successful! Please log in as {user.username}.")
                logout(request)
                return redirect('login')
                
            return render(request, self.template_step2, {'form': form})


def public_wholesale_request_view(request):
    """
    Public view for non-logged-in users to request a wholesale account.
    """
    if request.method == 'POST':
        company_name = request.POST.get('company_name')
        business_address = request.POST.get('business_address')
        contact_name = request.POST.get('contact_name')
        contact_email = request.POST.get('contact_email')
        wholesaler_email = request.POST.get('wholesaler_email')

        # Priority: Database setting -> settings.py hardcoded
        recipient_email = SystemSetting.get_val('wholesale_recipient', getattr(settings, 'WHOLESALE_ONBOARDING_RECIPIENT', 'subham@yopmail.com'))

        try:
            # Prepare context for the polished email template
            # We pass a dictionary that mimics the company object structure used in the template
            context = {
                'company': {
                    'name': company_name,
                    'full_address': business_address,
                    'email': wholesaler_email,
                },
                'user': {
                    'get_full_name': contact_name,
                    'username': wholesaler_email,
                },
                'receiver_email': contact_email
            }
            
            html_message = render_to_string('emails/wholesale_account_request.html', context)
            subject = f"Public Wholesale Request: {company_name}"
            
            send_mail(
                subject=subject,
                message=f"Public Wholesale Request from {company_name}. Please see HTML version.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            messages.success(request, "Success! Your wholesale request has been sent to our team. We'll be in touch soon.")
            logger.info(f"Public wholesale request sent from {company_name} ({contact_email})")
            return redirect('accounts:public_wholesale_request')
            
        except Exception as e:
            messages.error(request, f"Oops! We couldn't send your request right now. Please try again later.")
            logger.error(f"Failed to process public wholesale request: {str(e)}")

    return render(request, 'accounts/public_wholesale_request.html')
