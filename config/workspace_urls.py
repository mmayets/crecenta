"""Todas las rutas de dominio, montadas bajo /e/<uuid:ws>/.

Cada app agrega aquí su `ws_urls`. El test de aislamiento recorre este módulo y verifica que
ninguna ruta sea accesible desde un espacio ajeno.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.workspaces.ws_urls")),
    path("", include("apps.ledger.ws_urls")),
    path("", include("apps.planning.ws_urls")),
    path("", include("apps.alerts.ws_urls")),
    path("", include("apps.receipts.ws_urls")),
    path("", include("apps.onboarding.ws_urls")),
    path("", include("apps.business.ws_urls")),
]
