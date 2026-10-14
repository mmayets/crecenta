from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.workspaces import views as workspace_views

urlpatterns = [
    path("", workspace_views.home, name="home"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("cuenta/", include("apps.accounts.urls")),
    path("cuenta/", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.pwa.urls")),
    path("", include("apps.workspaces.urls")),
    path("", include("apps.onboarding.urls")),
    path("e/<uuid:ws>/", include("config.workspace_urls")),
]
# Los archivos subidos (comprobantes) nunca se sirven como estáticos públicos: solo a través de la
# vista autenticada de cada comprobante.
