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
    data that doesn't belong to their company.
    """
    if user.role == 'customer' and user.company:
        if obj_company != user.company:
            logger.warning(
                f'SECURITY: {user.username} (company: {user.company}) '
                f'tried to access data of company: {obj_company}'
            )
            raise PermissionDenied("You do not have access to this record.")
