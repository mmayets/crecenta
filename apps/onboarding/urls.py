"""Rutas del asistente de espacios (no dependen de un espacio: aún puede no existir ninguno)."""

from django.urls import path

from . import assistant_views as views

app_name = "asistente"

urlpatterns = [
    path("asistente/", views.chat, name="chat"),
    path("asistente/crear/", views.create, name="create"),
    path("asistente/saltar/", views.skip, name="skip"),
    path("asistente/reiniciar/", views.restart, name="restart"),
    path("asistente/ia/", views.enable_ai, name="enable_ai"),
    path("asistente/voz/", views.voice, name="voice"),
]
