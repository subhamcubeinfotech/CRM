from django.conf import settings

def map_config(request):
    """
    Context processor to provide map configuration to templates.
    """
    return {
        'MAP_GEOCODING_API_URL': settings.MAP_GEOCODING_API_URL,
        'MAP_TILE_SERVER_URL': settings.MAP_TILE_SERVER_URL,
    }
