from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.views import View
from .forms import SignupStep1Form, SignupStep2Form
from .models_tenant import Tenant
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
