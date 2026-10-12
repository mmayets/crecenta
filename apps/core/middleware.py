from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

# Política de contenido: todo se sirve localmente (sin CDN). htmx y Alpine requieren
# 'unsafe-eval' solo si se usan expresiones dinámicas de Alpine; se usa la build CSP de Alpine.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "worker-src 'self'",
        "manifest-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)
PERMISSIONS_POLICY = "camera=(self), microphone=(self), geolocation=(), payment=()"


class SecurityHeadersMiddleware:
    """Cabeceras de seguridad que Django no agrega por sí solo."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response
