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
        
        # In a real scenario, you might want to get the user's email
        # For now, we assume the user was just created and we might have their email in session or just use tenant info
        
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price': settings.STRIPE_PRICE_ID,
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                success_url=request.build_absolute_uri(reverse('accounts:signup_success')),
                cancel_url=request.build_absolute_uri(reverse('accounts:signup_cancel')),
                client_reference_id=str(tenant.id),
                metadata={
                    'tenant_id': tenant.id,
                }
            )
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            logger.error(f"Error creating Stripe session: {str(e)}")
            return render(request, 'registration/error.html', {'message': "Could not initiate payment. Please try again later."})

class SignupSuccessView(View):
    def get(self, request):
        return render(request, 'registration/signup_success_pending.html')

class SignupCancelView(View):
    def get(self, request):
        return render(request, 'registration/signup_cancel.html')

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
            
            tenant_id = session.client_reference_id
            stripe_customer_id = session.customer
            stripe_subscription_id = session.subscription

            if tenant_id:
                try:
                    tenant = Tenant.objects.get(id=tenant_id)
                    
                    # Fetch subscription details from Stripe to get period end
                    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
                    expiry_date = timezone.make_aware(datetime.datetime.fromtimestamp(stripe_sub.current_period_end))

                    # Update or create subscription
                    subscription, created = Subscription.objects.get_or_create(tenant=tenant)
                    subscription.stripe_customer_id = stripe_customer_id
                    subscription.stripe_subscription_id = stripe_subscription_id
                    subscription.status = 'active'
                    subscription.is_active = True
                    subscription.expiry_date = expiry_date
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
                
                # Deactivate Tenant and Users
                tenant = subscription.tenant
                tenant.is_active = False
                tenant.save()
                
                User = get_user_model()
                User.objects.filter(tenant=tenant).update(is_active=False)
                
                logger.info(f"Tenant {tenant.name} deactivated because subscription was canceled.")
            except Subscription.DoesNotExist:
                logger.error(f"Webhook error: Subscription {stripe_subscription_id} not found in DB.")

        return HttpResponse(status=200)
