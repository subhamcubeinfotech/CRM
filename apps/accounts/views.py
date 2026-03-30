"""
Accounts Views
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.mail import EmailMessage
from django.conf import settings
from .models import Company
from .forms import CompanyForm
from .geocoding import geocode_company
from .utils import filter_by_user_company, check_company_access
from django.db.models import Q
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
    if request.user.role == 'admin':
        for company in companies:
            if company.full_address and (company.latitude is None or company.longitude is None):
                geocode_company(company, save=True)
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
    
    from apps.orders.models import Order
    from apps.shipments.models import Shipment
    
    orders = Order.objects.filter(
        Q(supplier=company) | Q(receiver=company)
    ).order_by('-created_at')[:20]

    shipments = Shipment.objects.filter(
        Q(customer=company) | Q(carrier=company) | Q(shipper=company) | Q(consignee=company)
    ).order_by('-created_at')[:20]

    # Construct locations list (Only Company primary address as per user request)
    locations = []
    if company.address_line1:
        locations.append({
            'name': f"Main Office - {company.name}",
            'code': 'HQ',
            'full_address': company.full_address,
            'city': company.city,
            'state': company.state,
            'country': company.country,
            'is_warehouse': False,
            'phone': company.phone,
            'email': company.email
        })

    from apps.inventory.models import Material
    materials = Material.objects.all()[:10]  # Placeholder: Get some materials for now

    context = {
        'company': company,
        'shipments': shipments,
        'orders': orders,
        'locations': locations,
        'materials': materials,
    }
    return render(request, 'accounts/company_detail.html', context)


@login_required
def company_edit(request, pk):
    """Edit an existing company"""
    company = get_object_or_404(Company, pk=pk)
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES, instance=company, user=request.user)
        if form.is_valid():
            company = form.save()
            geocode_company(company, save=True)
            logger.info(f'Company updated: {company.name} (ID: {pk}) by {request.user}')
            return redirect('accounts:company_detail', pk=pk)
        else:
            logger.warning(f'Company edit form invalid for ID {pk}: {form.errors}')
    else:
        form = CompanyForm(instance=company, user=request.user)
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
        form = CompanyForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            company = form.save(commit=False)
            if hasattr(request.user, 'tenant'):
                company.tenant = request.user.tenant
            company.save()
            geocode_company(company, save=True)
            
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
        
        form = CompanyForm(initial=initial_data, user=request.user)
        
    context = {
        'form': form,
        'title': 'Add Company',
        'is_edit': False
    }
    return render(request, 'accounts/company_form.html', context)


@login_required
@require_POST
def ajax_help_ticket(request):
    """Create a lightweight support ticket by sending an email."""
    ticket_type = (request.POST.get('ticket_type') or '').strip().lower()
    notify_email = (request.POST.get('notify_email') or '').strip()
    title = (request.POST.get('title') or '').strip()
    description = (request.POST.get('description') or '').strip()
    steps = (request.POST.get('steps') or '').strip()

    if ticket_type not in {'suggestion', 'bug'}:
        return JsonResponse({'success': False, 'message': 'Invalid ticket type.'}, status=400)

    if not notify_email or not title or not description:
        return JsonResponse({'success': False, 'message': 'Please fill all required fields.'}, status=400)

    if ticket_type == 'bug' and not steps:
        return JsonResponse({'success': False, 'message': 'Steps to reproduce are required for bug reports.'}, status=400)

    subject_prefix = 'Suggestion' if ticket_type == 'suggestion' else 'Bug Report'
    subject = f'{subject_prefix}: {title}'
    body_lines = [
        f'Ticket Type: {subject_prefix}',
        f'Raised By: {request.user.get_full_name() or request.user.username}',
        f'Username: {request.user.username}',
        f'Notify Email: {notify_email}',
        '',
        f'Title: {title}',
        '',
        'Description:',
        description,
    ]

    if ticket_type == 'bug':
        body_lines.extend([
            '',
            'Steps to Reproduce:',
            steps,
        ])

    try:
        email = EmailMessage(
            subject=subject,
            body='\n'.join(body_lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=['subham32032@gmail.com'],
            reply_to=[notify_email],
        )
        email.send(fail_silently=False)
    except Exception as exc:
        logger.exception('Failed to send help ticket email: %s', exc)
        return JsonResponse({'success': False, 'message': 'Failed to send ticket email.'}, status=500)

    return JsonResponse({
        'success': True,
        'message': 'Ticket created and email sent successfully.',
    })
