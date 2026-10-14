"""Rutas del asistente de espacios (no dependen de un espacio: aún puede no existir ninguno)."""

from django.urls import path

from . import assistant_views as views
from . import first_space_views

app_name = "asistente"

urlpatterns = [
    path("asistente/", views.chat, name="chat"),
    path("asistente/crear/", views.create, name="create"),
    path("asistente/saltar/", views.skip, name="skip"),
    path("asistente/reiniciar/", views.restart, name="restart"),
    path("asistente/ia/", views.enable_ai, name="enable_ai"),
    path("asistente/voz/", views.voice, name="voice"),
    # Crear otro espacio: elegir entre tarjetas guiadas y chat.
    path("asistente/nuevo-espacio/", first_space_views.new_space, name="new_space"),
    # Primer espacio: paso a paso con tarjetas (la entrada de quien aún no tiene espacios).
    path("asistente/primer-espacio/", first_space_views.wizard, name="first_space"),
    path("asistente/primer-espacio/crear/", first_space_views.create, name="first_space_create"),
    path(
        "asistente/primer-espacio/reiniciar/",
        first_space_views.restart,
        name="first_space_restart",
    ),
    path(
        "asistente/primer-espacio/<slug:step>/", first_space_views.wizard, name="first_space_step"
    ),
]
