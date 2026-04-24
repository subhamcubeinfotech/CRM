import stripe
import logging
from django.conf import settings
from django.urls import reverse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
import datetime
from .models_tenant import Tenant
from .models_subscription import Subscription

logger = logging.getLogger('apps.accounts')
stripe.api_key = settings.STRIPE_SECRET_KEY

class CreateCheckoutSessionView(View):
    def get(self, request, tenant_id, *args, **kwargs):
        tenant = get_object_or_404(Tenant, id=tenant_id)
        plan_type = request.GET.get('plan', 'starter')  # Default to starter
        
        # Select price and trial days
        if plan_type == 'pro':
            price_id = settings.STRIPE_PRICE_PROFESSIONAL
            trial_days = 3  # 3 days trial for Professional plan
            plan_name = 'professional'
        else:
            price_id = settings.STRIPE_PRICE_STARTER
            trial_days = None
            plan_name = 'starter'

        try:
            checkout_params = {
                'payment_method_types': ['card'],
                'line_items': [
                    {
                        'price': price_id,
                        'quantity': 1,
                    },
                ],
                'mode': 'subscription',
                'success_url': request.build_absolute_uri(reverse('accounts:signup_success')) + '?session_id={CHECKOUT_SESSION_ID}',
                'cancel_url': request.build_absolute_uri(reverse('accounts:signup_cancel')),
                'client_reference_id': str(tenant.id),
                'metadata': {
                    'tenant_id': tenant.id,
                    'plan_name': plan_name,
                }
            }

            if trial_days:
                checkout_params['subscription_data'] = {
                    'trial_period_days': trial_days,
                }

            checkout_session = stripe.checkout.Session.create(**checkout_params)
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            logger.error(f"Error creating Stripe session: {str(e)}")
            return render(request, 'registration/error.html', {'message': "Could not initiate payment. Please try again later."})

class SignupSuccessView(View):
    def get(self, request):
        session_id = request.GET.get('session_id')
        
        if session_id:
            try:
                # Retrieve the checkout session from Stripe
                session = stripe.checkout.Session.retrieve(session_id)
                tenant_id = session.client_reference_id
                stripe_customer_id = session.customer
                stripe_subscription_id = session.subscription
                
                # Safely access metadata (StripeObject does not support .get())
                metadata = getattr(session, 'metadata', None)
                plan_name = 'starter'
                if metadata:
                    try:
                        plan_name = metadata['plan_name']
                    except (KeyError, TypeError):
                        plan_name = 'starter'
                
                logger.info(f"Success redirect: tenant_id={tenant_id}, plan={plan_name}, sub_id={stripe_subscription_id}")
                
                if tenant_id and stripe_subscription_id:
                    tenant = Tenant.objects.get(id=tenant_id)
                    
                    # Fetch subscription details from Stripe
                    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
                    
                    # Safely get expiry date
                    period_end = getattr(stripe_sub, 'current_period_end', None)
                    if not period_end:
                        try:
                            period_end = stripe_sub['current_period_end']
                        except (KeyError, TypeError):
                            period_end = None
                    
                    expiry_date = None
                    if period_end:
                        expiry_date = timezone.make_aware(datetime.datetime.fromtimestamp(period_end))
                    
                    # Update or create subscription
                    subscription, created = Subscription.objects.get_or_create(tenant=tenant)
                    subscription.stripe_customer_id = stripe_customer_id
                    subscription.stripe_subscription_id = stripe_subscription_id
                    subscription.status = 'active'
                    subscription.is_active = True
                    if expiry_date:
                        subscription.expiry_date = expiry_date
                    subscription.plan = plan_name
                    subscription.save()
                    
                    # Activate Tenant and Users
                    tenant.is_active = True
                    tenant.save()
                    
                    User = get_user_model()
                    User.objects.filter(tenant=tenant).update(is_active=True)
                    
                    logger.info(f"Tenant {tenant.name} activated via success redirect.")
            except Exception as e:
                import traceback
                logger.error(f"Error processing success redirect: {str(e)}\n{traceback.format_exc()}")
        
        return render(request, 'registration/signup_success_pending.html')

class SignupCancelView(View):
    def get(self, request):
        return render(request, 'registration/signup_cancel.html')

class SubscriptionExpiredView(LoginRequiredMixin, View):
    def get(self, request):
        # Always fetch the latest subscription status directly from the DB
        # to ensure they aren't stuck here if they just renewed.
        tenant = getattr(request.user, 'tenant', None)
        if tenant:
            subscription = getattr(tenant, 'subscription', None)
            if subscription and subscription.is_active:
                return redirect('dashboard')
        return render(request, 'accounts/subscription_expired.html')

class CreatePortalSessionView(View):
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        subscription = getattr(request.user.tenant, 'subscription', None)
        if not subscription or not subscription.stripe_customer_id:
            messages.error(request, "No active subscription found.")
            return redirect('accounts:settings')

        try:
            # Authenticate with Stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            # Create a portal session
            portal_session = stripe.billing_portal.Session.create(
                customer=subscription.stripe_customer_id,
                return_url=request.build_absolute_uri(reverse('accounts:settings')),
            )
            return redirect(portal_session.url, code=303)
        except Exception as e:
            logger.error(f"Error creating Portal session: {str(e)}")
            messages.error(request, "Could not open billing portal. Please try again later.")
            return redirect('accounts:settings')


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(View):
    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        event = None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError as e:
            return HttpResponse(status=400)

        # Handle the checkout.session.completed event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            tenant_id = session.get('client_reference_id', None) if isinstance(session, dict) else session.client_reference_id
            stripe_customer_id = session.get('customer', None) if isinstance(session, dict) else session.customer
            stripe_subscription_id = session.get('subscription', None) if isinstance(session, dict) else session.subscription
            
            # Safely access metadata
            plan_name = 'starter'
            try:
                metadata = session.get('metadata', {}) if isinstance(session, dict) else getattr(session, 'metadata', None)
                if metadata:
                    plan_name = metadata.get('plan_name', 'starter') if isinstance(metadata, dict) else metadata['plan_name']
            except (KeyError, TypeError, AttributeError):
                plan_name = 'starter'

            if tenant_id:
                try:
                    tenant = Tenant.objects.get(id=tenant_id)
                    
                    # Fetch subscription details from Stripe to get period end
                    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
                    
                    # Safely get expiry date
                    period_end = getattr(stripe_sub, 'current_period_end', None)
                    if not period_end:
                        try:
                            period_end = stripe_sub['current_period_end']
                        except (KeyError, TypeError):
                            period_end = None
                    
                    expiry_date = None
                    if period_end:
                        expiry_date = timezone.make_aware(datetime.datetime.fromtimestamp(period_end))

                    # Update or create subscription
                    subscription, created = Subscription.objects.get_or_create(tenant=tenant)
                    subscription.stripe_customer_id = stripe_customer_id
                    subscription.stripe_subscription_id = stripe_subscription_id
                    subscription.status = 'active'
                    subscription.is_active = True
                    if expiry_date:
                        subscription.expiry_date = expiry_date
                    subscription.plan = plan_name
                    subscription.save()

                    # Activate Tenant and Users
                    tenant.is_active = True
                    tenant.save()
                    
                    User = get_user_model()
                    User.objects.filter(tenant=tenant).update(is_active=True)
                    
                    logger.info(f"Tenant {tenant.name} activated via Stripe payment.")
                except Tenant.DoesNotExist:
                    logger.error(f"Webhook error: Tenant {tenant_id} not found.")

        # Handle subscription deletion
        elif event['type'] == 'customer.subscription.deleted':
            stripe_sub = event['data']['object']
            stripe_subscription_id = stripe_sub.id
            
            try:
                subscription = Subscription.objects.get(stripe_subscription_id=stripe_subscription_id)
                subscription.status = 'canceled'
                subscription.is_active = False
                subscription.save()
                
                # Note: We NO LONGER deactivate the Tenant or Users here.
                # Instead, the SubscriptionMiddleware will restrict their access
                # to the SubscriptionExpired page so they can renew.
                
                logger.info(f"Subscription {stripe_subscription_id} canceled for Tenant {subscription.tenant.name}.")
            except Subscription.DoesNotExist:
                logger.error(f"Webhook error: Subscription {stripe_subscription_id} not found in DB.")
                
        # Handle subscription updates (upgrades, downgrades, renewals)
        elif event['type'] == 'customer.subscription.updated':
            stripe_sub = event['data']['object']
            stripe_subscription_id = stripe_sub.id
            
            try:
                subscription = Subscription.objects.get(stripe_subscription_id=stripe_subscription_id)
                
                # Check status: 'active', 'trialing', 'past_due', 'canceled', 'unpaid'
                status = stripe_sub.get('status', 'active')
                
                # Retrieve the plan from the subscription item
                plan_name = 'starter'
                try:
                    items = stripe_sub.get('items', {}).get('data', [])
                    if items:
                        price_id = items[0].get('price', {}).get('id')
                        if price_id == settings.STRIPE_PRICE_PROFESSIONAL:
                            plan_name = 'professional'
                except Exception as e:
                    logger.error(f"Error reading plan from updated subscription: {e}")

                subscription.status = status
                subscription.plan = plan_name
                
                if status in ['active', 'trialing']:
                    subscription.is_active = True
                elif status in ['canceled', 'unpaid']:
                    subscription.is_active = False
                    
                # Safely get expiry date
                period_end = getattr(stripe_sub, 'current_period_end', None)
                if not period_end:
                    try:
                        period_end = stripe_sub['current_period_end']
                    except (KeyError, TypeError):
                        period_end = None
                
                if period_end:
                    subscription.expiry_date = timezone.make_aware(datetime.datetime.fromtimestamp(period_end))
                    
                subscription.save()
                logger.info(f"Subscription {stripe_subscription_id} updated: status={status}, plan={plan_name}.")
            except Subscription.DoesNotExist:
                # If it doesn't exist, it might be a new subscription that we'll catch in checkout.session.completed
                pass

        return HttpResponse(status=200)
