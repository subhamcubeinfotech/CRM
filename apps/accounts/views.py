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
from .models import Company, CompanyDocument
from .forms import CompanyForm
from apps.inventory.forms import WarehouseForm

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
    """List companies — filtered by creator unless admin (uses plain_objects)"""
    companies = Company.plain_objects.all().order_by('name')
    
    # Restriction: non-admins only see companies they created OR their own company
    if not getattr(request.user, 'is_admin', False):
        user_company = request.user.company
        if user_company:
            companies = companies.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            companies = companies.filter(created_by=request.user)
    
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
    """List customers — filtered by creator unless admin (uses plain_objects)"""
    customers = Company.plain_objects.filter(company_type='customer').order_by('name')
    
    # Restriction: non-admins only see companies they created OR their own company
    if not getattr(request.user, 'is_admin', False):
        user_company = request.user.company
        if user_company:
            customers = customers.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            customers = customers.filter(created_by=request.user)
    
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
    """List carriers — filtered by creator unless admin (uses plain_objects)"""
    carriers = Company.plain_objects.filter(company_type='carrier').order_by('name')
    
    # Restriction: non-admins only see companies they created OR their own company
    if not getattr(request.user, 'is_admin', False):
        user_company = request.user.company
        if user_company:
            carriers = carriers.filter(Q(created_by=request.user) | Q(pk=user_company.pk))
        else:
            carriers = carriers.filter(created_by=request.user)
    
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
    company = get_object_or_404(Company.plain_objects, pk=pk)
    
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

    documents = company.documents.all()

    context = {
        'company': company,
        'shipments': shipments,
        'orders': orders,
        'locations': locations,
        'materials': materials,
        'documents': documents,
        'location_form': WarehouseForm(initial={'company': company}),
    }
    return render(request, 'accounts/company_detail.html', context)


@login_required
def company_edit(request, pk):
    """Edit an existing company"""
    company = get_object_or_404(Company.plain_objects, pk=pk)
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
    company = get_object_or_404(Company.plain_objects, pk=pk)
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
            company.created_by = request.user
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

@login_required
@require_POST
def company_document_upload(request, pk):
    """AJAX upload for company documents"""
    company = get_object_or_404(Company, pk=pk)
    # Check access
    if request.user.role == 'customer':
        check_company_access(company, request.user)
    
    if request.FILES.get('file'):
        file = request.FILES['file']
        doc_type = request.POST.get('document_type', 'other')
        title = request.POST.get('title', file.name)
        
        document = CompanyDocument.objects.create(
            company=company,
            document_type=doc_type,
            title=title,
            file=file,
            uploaded_by=request.user,
            tenant=company.tenant
        )
        
        return JsonResponse({
            'success': True,
            'document': {
                'id': document.id,
                'title': document.title,
                'type_display': document.get_document_type_display(),
                'url': document.file.url,
                'uploaded_at': document.uploaded_at.strftime('%b %d, %Y'),
                'uploaded_by': document.uploaded_by.get_full_name() or document.uploaded_by.username
            }
        })
    return JsonResponse({'success': False, 'message': 'No file provided'}, status=400)


@login_required
@require_POST
def company_document_delete(request, doc_pk):
    """AJAX delete for company documents"""
    document = get_object_or_404(CompanyDocument, pk=doc_pk)
    
    # Check access
    if request.user.role == 'customer':
        check_company_access(document.company, request.user)
    
    document.delete()
    return JsonResponse({'success': True})
