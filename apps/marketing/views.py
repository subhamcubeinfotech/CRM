import stripe
import logging
from django.conf import settings
from django.views.generic import TemplateView, View
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

logger = logging.getLogger('apps.accounts')

# Configure Stripe globally if possible, or set it via settings
# stripe.api_key = settings.STRIPE_SECRET_KEY

class HomeView(TemplateView):
    template_name = 'marketing/home.html'

class PricingView(TemplateView):
    template_name = 'marketing/pricing.html'

class FeaturesView(TemplateView):
    template_name = 'marketing/features.html'

class StripeCheckoutView(View):
    def post(self, request, *args, **kwargs):
        logger.info(f'Stripe checkout initiated by {request.user}')
        return JsonResponse({'checkout_url': 'https://checkout.stripe.com/pay/...'})

class StripeSuccessView(TemplateView):
    template_name = 'marketing/checkout_success.html'

class StripeCancelView(TemplateView):
    template_name = 'marketing/checkout_cancel.html'

@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(View):
    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        logger.info('Stripe webhook received')
        # event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
        # handle event...
        return HttpResponse(status=200)
