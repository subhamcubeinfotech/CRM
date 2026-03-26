from django.apps import AppConfig

class ShipmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.shipments'
    verbose_name = 'Shipments Management'

    def ready(self):
        import apps.shipments.signals
