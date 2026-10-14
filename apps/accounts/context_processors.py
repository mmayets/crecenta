from django.conf import settings
from django.http import HttpRequest


def push(request: HttpRequest) -> dict:
    """Clave pública VAPID para que el navegador pueda suscribirse a las notificaciones push."""
    return {"vapid_public_key": settings.VAPID_PUBLIC_KEY}
