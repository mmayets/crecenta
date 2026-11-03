from django.urls import path

from . import views

app_name = "sies"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("calificaciones/", views.calificaciones, name="calificaciones"),
    path("calificaciones/publicar/", views.publicar, name="publicar"),
    path("asistencia/", views.asistencia, name="asistencia"),
    path("estudiantes/", views.estudiantes, name="estudiantes"),
    path("calendario/", views.calendario, name="calendario"),
    path("exportar/", views.exportar, name="exportar"),
]
