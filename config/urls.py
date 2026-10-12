from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.workspaces import views as workspace_views

urlpatterns = [
    path("", workspace_views.home, name="home"),
    path("admin/", admin.site.urls),
    path("cuenta/", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.workspaces.urls")),
    path("e/<uuid:ws>/", include("config.workspace_urls")),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
