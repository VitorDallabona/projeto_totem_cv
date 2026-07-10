import os
from django.core.asgi import get_asgi_application

# Corrigido: usando 'totem_project.settings'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'totem_project.settings')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import students.routing 

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            students.routing.websocket_urlpatterns
        )
    ),
})