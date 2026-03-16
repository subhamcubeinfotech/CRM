"""
Accounts Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.core.paginator import Paginator
from .models import Company, SystemSetting
from .forms import CompanyForm
from .utils import filter_by_user_company, check_company_access
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib import messages
import logging

logger = logging.getLogger('apps.accounts')


def custom_logout(request):
    """Log out the user and redirect to login page"""
    logout(request)
    return redirect('login')


@login_required
def company_list(request):
    """List all companies — filtered by tenant (handled by TenantManager)"""
    companies = Company.objects.all().order_by('name')
    
    # Filter by type
    company_type = request.GET.get('type')
    if company_type:
        companies = companies.filter(company_type=company_type)
        
    # Search
    search = request.GET.get('search')
    if search:
        companies = companies.filter(name__icontains=search)

    company_type = request.GET.get('type')
    search = request.GET.get('search')
    paginator = Paginator(companies, 25)
    page = request.GET.get('page')
    companies = paginator.get_page(page)
    context = {
        'companies': companies,
        'company_type': company_type,
        'search': search,
    }
    return render(request, 'accounts/company_list.html', context)


@login_required
def customer_list(request):
    """List all customers"""
    customers = Company.objects.filter(company_type='customer').order_by('name')
    
    # Search
    search = request.GET.get('search')
    if search:
        customers = customers.filter(name__icontains=search)
    
    paginator = Paginator(customers, 25)
    page = request.GET.get('page')
    customers = paginator.get_page(page)
    
    context = {
        'customers': customers,
        'search': search,
    }
    return render(request, 'accounts/customer_list.html', context)


@login_required
def carrier_list(request):
    """List all carriers"""
    carriers = Company.objects.filter(company_type='carrier').order_by('name')
    
    # Search
    search = request.GET.get('search')
    if search:
        carriers = carriers.filter(name__icontains=search)
    
    paginator = Paginator(carriers, 25)
    page = request.GET.get('page')
    carriers = paginator.get_page(page)
    
    context = {
        'carriers': carriers,
        'search': search,
    }
    return render(request, 'accounts/carrier_list.html', context)


@login_required
def company_detail(request, pk):
    """View company details"""
    company = get_object_or_404(Company, pk=pk)
    # Customer can only view their own company or companies in their tenant
    if request.user.role == 'customer':
        check_company_access(company, request.user)
    
    context = {
        'company': company,
        'shipments': company.shipments_as_customer.all()[:10] if company.company_type == 'customer' else None,
        'invoices': company.invoices.all()[:10] if company.company_type == 'customer' else None,
    }
    return render(request, 'accounts/company_detail.html', context)


@login_required
def company_edit(request, pk):
    """Edit an existing company"""
    company = get_object_or_404(Company, pk=pk)
    if request.method == 'POST':
        form = CompanyForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            logger.info(f'Company updated: {company.name} (ID: {pk}) by {request.user}')
            return redirect('accounts:company_detail', pk=pk)
        else:
            logger.warning(f'Company edit form invalid for ID {pk}: {form.errors}')
    else:
        form = CompanyForm(instance=company)
    context = {
        'form': form,
        'company': company,
        'title': f'Edit {company.name}',
        'is_edit': True
    }
    return render(request, 'accounts/company_form.html', context)


@login_required
def company_delete(request, pk):
    """Delete a company"""
    company = get_object_or_404(Company, pk=pk)
    if request.method == 'POST':
        name = company.name
        company.delete()
        logger.info(f'Company deleted: {name} (ID: {pk}) by {request.user}')
        return redirect('accounts:company_list')
    context = {'company': company}
    return render(request, 'accounts/company_confirm_delete.html', context)


@login_required
def company_create(request):
    """Create a new company"""
    if request.method == 'POST':
        form = CompanyForm(request.POST)
        if form.is_valid():
            company = form.save(commit=False)
            if hasattr(request.user, 'tenant'):
                company.tenant = request.user.tenant
            company.save()
            
            # Create a default warehouse location if address is provided
            if company.address_line1 or company.city:
                from apps.inventory.models import Warehouse
                Warehouse.objects.create(
                    name=f"Main Office - {company.name}",
                    code=f"{company.name[:3].upper()}-{company.pk}",
                    address=company.address_line1,
                    city=company.city,
                    state=company.state,
                    country=company.country,
                    postal_code=company.postal_code,
                    company=company,
                    tenant=company.tenant
                )
            
            return redirect('accounts:company_list')
    else:
        # Pre-select company type if passed in URL
        initial_data = {}
        company_type = request.GET.get('type')
        if company_type in [choice[0] for choice in Company.COMPANY_TYPE_CHOICES]:
            initial_data['company_type'] = company_type
        
        form = CompanyForm(initial=initial_data)
        
    context = {
        'form': form,
        'title': 'Add Company',
        'is_edit': False
    }
    return render(request, 'accounts/company_form.html', context)


@login_required
def wholesale_request_view(request, pk):
    """
    Handles a request to Urban Poling for a wholesale account tier.
    Only accessible via POST for security.
    """
    company = get_object_or_404(Company, pk=pk)
    
    # Access control
    if request.user.role == 'customer':
        check_company_access(company, request.user)
    
    if request.method == 'POST':
        recipient_email = SystemSetting.get_val('wholesale_recipient', getattr(settings, 'WHOLESALE_ONBOARDING_RECIPIENT', 'subham@yopmail.com'))
        
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
            messages.success(request, f"Wholesale account request for {company.name} sent successfully.")
            logger.info(f'Wholesale request sent for {company.name} (ID: {pk}) by {request.user} to {recipient_email}')
        except Exception as e:
            messages.error(request, f"Could not send request: {str(e)}")
            logger.error(f'Critical error sending wholesale request for {company.name}: {e}')
            
    return redirect('accounts:company_detail', pk=pk)
