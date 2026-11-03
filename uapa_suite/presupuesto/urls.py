from django.urls import path

from . import views

app_name = "presupuesto"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("solicitudes/", views.solicitudes, name="solicitudes"),
    path("solicitudes/nueva/", views.nueva_solicitud, name="nueva_solicitud"),
    path("solicitudes/<int:numero>/decidir/", views.decidir, name="decidir"),
    path("partidas/", views.partidas, name="partidas"),
    path("partidas/exportar/", views.exportar_partidas, name="exportar_partidas"),
    path("reportes/", views.reportes, name="reportes"),
    path("proveedores/", views.proveedores, name="proveedores"),
]
