import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from .engine import process_query
from .models import ChatSession, ChatMessage

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        
        # Reject unauthenticated connections
        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close()
            return
            
        await self.accept()
        
        # Get or create active session
        self.session = await self.get_active_session()
        
    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get('message', '').strip()
        
        if not message:
            return

        # Start generating reply message (simulate typing delay naturally)
        
        # Save user message
        await self.save_message('user', message)
        
        # Process the query using the AI engine (runs synchronously, so wrap in database_sync_to_async)
        try:
            response_text = await self.process_ai_query(message)
        except Exception as e:
            response_text = "⚠️ Sorry, I encountered an error processing your request. Please try again."
            
        # Save assistant message
        await self.save_message('assistant', response_text)
        
        # Send message back to WebSocket
        await self.send(text_data=json.dumps({
            'response': response_text,
            'role': 'assistant',
        }))

    @database_sync_to_async
    def get_active_session(self):
        session, _ = ChatSession.objects.get_or_create(
            user=self.user,
            tenant=self.user.tenant,
            is_active=True,
            defaults={'title': 'New Chat'}
        )
        return session

    @database_sync_to_async
    def save_message(self, role, content):
        if role == 'user' and self.session.messages.filter(role='user').count() == 0:
             self.session.title = content[:80]
             self.session.save(update_fields=['title', 'updated_at'])
        return ChatMessage.objects.create(session=self.session, role=role, content=content)
        
    @database_sync_to_async
    def process_ai_query(self, message):
         return process_query(self.user, message)
