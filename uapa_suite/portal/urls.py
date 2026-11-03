from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("pendientes/", views.pendientes, name="pendientes"),
    path("pendientes/<int:pk>/alternar/", views.alternar_pendiente, name="alternar_pendiente"),
    path("notificaciones/", views.notificaciones, name="notificaciones"),
    path("notificaciones/leidas/", views.marcar_leidas, name="marcar_leidas"),
    path("buscar/", views.buscar, name="buscar"),
]
