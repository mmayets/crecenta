from django.urls import path

from . import views

app_name = "pwa"

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("sin-conexion/", views.offline, name="offline"),
    path("sin-conexion/guardado/", views.offline_saved, name="offline_saved"),
    path("registrar/", views.quick_entry, name="quick_entry"),
]
