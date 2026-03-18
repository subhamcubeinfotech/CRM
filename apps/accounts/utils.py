"""
Access control utilities — role-based data filtering helpers
"""
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger('apps.accounts')


def is_staff_user(user):
    """Returns True if user is admin/sales/warehouse (sees all data)"""
    return user.role in ('admin', 'sales', 'warehouse', 'driver')


def filter_by_user_company(queryset, user, company_field='customer'):
    """
    Filter queryset to only include records belonging to the user's company.
    Staff / admin users get all records unfiltered.
    """
    if user.is_authenticated and user.role == 'customer' and user.company:
        logger.debug(f'Data filter applied for {user.username} → company: {user.company}')
        return queryset.filter(**{company_field: user.company})
    return queryset


def check_company_access(obj_company, user):
    """
    Raise PermissionDenied if a customer user tries to access
    data that doesn't belong to their tenant.
    """
    if user.role == 'customer':
        # Allow access if same company OR same tenant
        if user.company and obj_company == user.company:
            return
        
        if user.tenant and obj_company.tenant == user.tenant:
            return
            
        # If user has a company assigned, but trying to access something outside their tenant/company
        if user.company:
            logger.warning(
                f'SECURITY: {user.username} (company: {user.company}) '
                f'tried to access data of company: {obj_company}'
            )
            raise PermissionDenied("You do not have access to this record.")
import random
import string
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

def generate_otp(length=6):
    """Generate a random numeric OTP"""
    return ''.join(random.choices(string.digits, k=length))

def send_otp_email(email, otp):
    """Send OTP to the user's email"""
    subject = f'{otp} is your FreightPro verification code'
    message = f'''Hello,

Thank you for choosing FreightPro! 

Your verification code is: {otp}

This code will expire in 5 minutes. Please enter it to complete your registration.

If you didn't request this code, you can safely ignore this email.

Thanks,
The FreightPro Team'''
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger = logging.getLogger('apps.accounts')
        logger.error(f"Failed to send OTP email to {email}: {str(e)}")
        return False
