from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "UAPA Suite · Administración"
admin.site.site_title = "UAPA Suite"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("acceso/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("popin/", include("popin.urls")),
    path("gth/", include("gth.urls")),
    path("presupuesto/", include("presupuesto.urls")),
    path("sies/", include("sies.urls")),
    path("", include("portal.urls")),
]
