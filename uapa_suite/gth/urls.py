from django.urls import path

from . import views

app_name = "gth"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("solicitudes/", views.solicitudes, name="solicitudes"),
    path("solicitudes/nueva/", views.nueva_solicitud, name="nueva_solicitud"),
    path("vacaciones/", views.vacaciones, name="vacaciones"),
    path("volantes/", views.volantes, name="volantes"),
    path("evaluacion/", views.evaluacion, name="evaluacion"),
    path("capacitaciones/", views.capacitaciones, name="capacitaciones"),
    path("certificaciones/", views.certificaciones, name="certificaciones"),
]
