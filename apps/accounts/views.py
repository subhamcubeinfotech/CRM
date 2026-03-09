"""
Accounts Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.core.paginator import Paginator
from .models import Company
from .forms import CompanyForm
def custom_logout(request):
    """Log out the user and redirect to login page"""
    logout(request)
    return redirect('login')


@login_required
def company_list(request):
    """List all companies"""
    companies = Company.objects.all().order_by('name')
    
    # Filter by type
    company_type = request.GET.get('type')
    if company_type:
        companies = companies.filter(company_type=company_type)
    
    # Search
    search = request.GET.get('search')
    if search:
        companies = companies.filter(name__icontains=search)
    
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
    
    context = {
        'company': company,
        'shipments': company.shipments_as_customer.all()[:10] if company.company_type == 'customer' else None,
        'invoices': company.invoices.all()[:10] if company.company_type == 'customer' else None,
    }
    return render(request, 'accounts/company_detail.html', context)


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
