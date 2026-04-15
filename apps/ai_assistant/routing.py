from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/ai_chat/', consumers.ChatConsumer.as_asgi()),
]
