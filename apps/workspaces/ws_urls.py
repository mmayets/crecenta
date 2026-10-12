"""Rutas bajo /e/<uuid:ws>/ (requieren membresía en el espacio)."""

from django.urls import path

from . import views

app_name = "espacio"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ajustes/", views.settings_hub, name="settings"),
]
