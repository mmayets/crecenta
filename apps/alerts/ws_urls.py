from django.urls import path

from . import views

app_name = "alerts"

urlpatterns = [
    path("alertas/", views.index, name="index"),
    path("alertas/reglas/", views.rules, name="rules"),
    path("alertas/<uuid:alert_id>/descartar/", views.dismiss, name="dismiss"),
    path("alertas/<uuid:alert_id>/resolver/", views.resolve, name="resolve"),
]
