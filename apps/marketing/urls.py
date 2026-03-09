from django.urls import path
from . import views

app_name = 'marketing'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('pricing/', views.PricingView.as_view(), name='pricing'),
    path('features/', views.FeaturesView.as_view(), name='features'),
    
    # Stripe endpoints
    path('checkout/', views.StripeCheckoutView.as_view(), name='checkout'),
    path('checkout/success/', views.StripeSuccessView.as_view(), name='checkout_success'),
    path('checkout/cancel/', views.StripeCancelView.as_view(), name='checkout_cancel'),
    path('webhook/stripe/', views.StripeWebhookView.as_view(), name='stripe_webhook'),
]
